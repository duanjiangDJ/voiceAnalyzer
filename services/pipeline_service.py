"""
pipeline_service.py — 流水线任务服务
===================================
直接调用现有 launcher.main，并为 UI 提供任务启动、日志、状态和进度事件。

支持多任务：每班级/单元可独立运行一个任务，通过 task_id 区分。
通过 asyncio.Queue 实现事件驱动的 SSE 推送（替代轮询）。

依赖:
    - asyncio, contextlib, io, threading, time, traceback, uuid（标准库）
    - services.app_context, services.class_service, services.log_service（项目内部模块）
"""

import asyncio
import contextlib
import io
import threading
import time
import traceback
import uuid

from services.app_context import get_app_context
from services.class_service import ClassService, DEFAULT_CLASS_ID, DEFAULT_UNIT_ID
from services.log_service import get_log_service
from src import launcher


_pipeline_service_instance: "PipelineService | None" = None
_pipeline_service_lock = threading.Lock()


class PipelineService:
    """流水线任务服务。每个实例管理一组独立的任务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.class_service = ClassService()
        self.log_service = get_log_service()
        self._lock = threading.RLock()
        # task_id -> task dict 的映射，支持多任务并发
        self._tasks: dict[str, dict] = {}
        # task_id -> asyncio.Queue 的事件队列，用于 SSE 推送
        self._queues: dict[str, asyncio.Queue] = {}
        # task_id -> threading.Event 的取消信号
        self._cancel_events: dict[str, threading.Event] = {}
        # 当前"活跃"的 task_id（兼容旧有单任务 API）
        self._current_task_id: str | None = None

    # ---- 任务生命周期 ----

    def start_task(self, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
        """启动完整评估任务。"""
        task_id = f"task_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        log_path = self.context.logs_dir / "tasks" / f"{task_id}.log"
        cancel_event = threading.Event()
        event_queue: asyncio.Queue = asyncio.Queue()

        task = {
            "task_id": task_id,
            "status": "running",
            "class_id": class_id,
            "unit_id": unit_id,
            "created_at": time.time(),
            "started_at": time.time(),
            "finished_at": None,
            "current_stage": "init",
            "events": [],
            "logs": ["任务已启动，正在调用 launcher.main"],
            "log_path": str(log_path),
            "_loop": None,  # SSE 连接后由 set_task_loop 注入
        }

        with self._lock:
            self._tasks[task_id] = task
            self._queues[task_id] = event_queue
            self._cancel_events[task_id] = cancel_event
            self._current_task_id = task_id

        self.log_service.append_task_line(task_id, "任务已启动，正在调用 launcher.main")

        # 推送初始事件
        self._push_event(task_id, {"type": "task_started", "task_id": task_id})

        thread = threading.Thread(
            target=self._run_launcher,
            args=(task_id, class_id, unit_id, cancel_event, event_queue),
            daemon=True,
        )
        thread.start()
        return task

    def _sanitize(self, task: dict | None) -> dict:
        """移除内部字段（`_` 前缀），确保 JSON 可序列化。"""
        if task is None:
            return {"status": "idle", "logs": [], "events": []}
        return {k: v for k, v in task.items() if not k.startswith("_")}

    def get_current_task(self) -> dict:
        """获取最近启动的任务快照（兼容旧 API）。"""
        with self._lock:
            if self._current_task_id and self._current_task_id in self._tasks:
                return self._sanitize(self._tasks[self._current_task_id])
            for tid in reversed(list(self._tasks.keys())):
                return self._sanitize(self._tasks[tid])
            return {"status": "idle", "logs": [], "events": []}

    def get_task(self, task_id: str) -> dict | None:
        """获取指定任务快照。"""
        with self._lock:
            task = self._tasks.get(task_id)
            return self._sanitize(task) if task else None

    def cancel_task(self, task_id: str) -> dict:
        """取消运行中的任务。"""
        with self._lock:
            cancel_event = self._cancel_events.get(task_id)
            task = self._tasks.get(task_id)
            if not cancel_event or not task:
                return {"cancelled": False, "reason": "任务不存在"}
            cancel_event.set()
            task.setdefault("logs", []).append("用户已请求取消任务，将在阶段边界停止。")
            self._push_event(task_id, {"type": "cancel_requested"})
        self.log_service.append_task_line(task_id, "用户已请求取消任务，将在阶段边界停止。", "WARNING")
        return {"cancelled": True}

    def get_logs(self, task_id: str) -> list[str]:
        """获取任务日志。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return []
            return list(task.get("logs", []))

    def get_queue(self, task_id: str) -> asyncio.Queue | None:
        """获取任务的事件队列（供 SSE 使用）。"""
        with self._lock:
            return self._queues.get(task_id)

    def set_task_loop(self, task_id: str, loop) -> None:
        """设置任务的事件循环引用，供后台线程安全推送事件。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["_loop"] = loop

    def cleanup_task(self, task_id: str) -> None:
        """清理已完成任务的资源（延迟 30s 执行以允许 SSE 读取最终状态）。"""
        def _delayed():
            time.sleep(30)
            with self._lock:
                self._queues.pop(task_id, None)
                self._cancel_events.pop(task_id, None)
        threading.Thread(target=_delayed, daemon=True).start()

    # ---- 内部 ----

    def _push_event(self, task_id: str, event: dict) -> None:
        """向事件队列推送（线程安全）。"""
        with self._lock:
            queue = self._queues.get(task_id)
            task = self._tasks.get(task_id)
            loop = task.get("_loop") if task else None
        if queue is None:
            return
        if loop and loop.is_running():
            loop.call_soon_threadsafe(lambda: queue.put_nowait(event) if not queue.full() else None)
        else:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _run_launcher(self, task_id: str, class_id: str, unit_id: str,
                      cancel_event: threading.Event, event_queue: asyncio.Queue) -> None:
        """后台调用 launcher.main 并收集输出。"""
        paths = self.class_service.unit_paths(class_id, unit_id)
        output = _LineCapture(lambda line: self._append_log(task_id, line))

        # 在后台线程中安全推送事件到 asyncio.Queue
        def progress_cb(event: dict) -> None:
            self._handle_progress_event(task_id, event)
            self._push_event(task_id, {"type": "task_update", "snapshot": self.get_task(task_id)})

        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                launcher.main(
                    class_id=class_id,
                    unit_id=unit_id,
                    paths_override={key: str(value) for key, value in paths.items() if key.endswith("_dir")},
                    progress_cb=progress_cb,
                    cancel_event=cancel_event,
                )
            status = "cancelled" if cancel_event.is_set() else "completed"
            self._finish_task(task_id, status, None)
        except SystemExit as exc:
            status = "completed" if exc.code in (0, None) else "failed"
            self._finish_task(task_id, status, exc.code)
        except Exception:
            self._append_log(task_id, traceback.format_exc(), "ERROR")
            self._finish_task(task_id, "failed", 1)

    def _append_log(self, task_id: str, line: str, level: str = "INFO") -> None:
        """写入内存日志和日志文件。"""
        clean_line = line.rstrip()
        if not clean_line:
            return
        self.log_service.append_task_line(task_id, clean_line, level)
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.setdefault("logs", []).append(clean_line)
                task["current_stage"] = self._infer_stage(clean_line, task.get("current_stage", "init"))

    def _handle_progress_event(self, task_id: str, event: dict) -> None:
        """处理 launcher 发送的结构化进度事件。"""
        self.log_service.append("task", "INFO", f"进度事件: {event.get('type')}", {"task_id": task_id, "event": event})
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.setdefault("events", []).append(event)
                if event.get("stage"):
                    task["current_stage"] = event["stage"]
                task["last_event"] = event

    def _finish_task(self, task_id: str, status: str, exit_code: int | None) -> None:
        """完成任务状态写入并触发延迟清理。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["status"] = status
                task["exit_code"] = exit_code
                task["finished_at"] = time.time()
                task.setdefault("logs", []).append(f"任务结束，状态: {status}")
        self.log_service.append_task_line(task_id, f"任务结束，状态: {status}")
        # 推送最终快照
        final_snapshot = self.get_task(task_id)
        if final_snapshot:
            self._push_event(task_id, {"type": "task_update", "snapshot": final_snapshot})
        # 延迟清理队列（给 SSE 30s 读取最终状态）
        self.cleanup_task(task_id)

    def _infer_stage(self, line: str, fallback: str = "init") -> str:
        """根据日志文本粗略推断当前阶段（辅助用，优先使用结构化事件）。"""
        stage_keywords = {
            "预检查": "filter_precheck",
            "语音": "voice_analysis",
            "Whisper": "whisper_transcribe",
            "LLM": "llm_compare",
            "后处理": "post_process",
            "可视化": "error_visualize",
            "归档": "history_snapshot",
        }
        for keyword, stage in stage_keywords.items():
            if keyword in line:
                return stage
        return fallback


class _LineCapture(io.TextIOBase):
    """将 stdout/stderr 的写入拆成行并回调。"""

    def __init__(self, on_line) -> None:
        self.on_line = on_line
        self.buffer = ""

    def write(self, text: str) -> int:
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.on_line(line)
        return len(text)

    def flush(self) -> None:
        if self.buffer:
            self.on_line(self.buffer)
            self.buffer = ""


def get_pipeline_service() -> PipelineService:
    """获取全局 PipelineService 单例，确保 API 与 SSE 共享同一任务队列。"""
    global _pipeline_service_instance
    with _pipeline_service_lock:
        if _pipeline_service_instance is None:
            _pipeline_service_instance = PipelineService()
        return _pipeline_service_instance
