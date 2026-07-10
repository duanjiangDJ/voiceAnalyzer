"""
log_service.py — UI 统一日志服务
===============================
将 API 操作、任务运行和系统事件统一写入 resource/logs，并提供前端读取能力。
使用模块级单例，避免重复创建实例。

依赖:
    - json, threading, time, pathlib（标准库）
    - services.app_context（项目内部模块）
"""

import json
import threading
import time
from pathlib import Path
from typing import Any

from services.app_context import get_app_context


_log_lock = threading.Lock()
_instance: "LogService | None" = None
_instance_lock = threading.Lock()


class LogService:
    """统一日志服务（单例）。"""

    def __init__(self) -> None:
        self.context = get_app_context()

    def append(self, channel: str, level: str, message: str,
               payload: dict[str, Any] | None = None) -> dict:
        """
        写入一条结构化日志。

        参数:
            channel: 日志通道，如 api、task、system
            level: 日志级别，如 INFO、WARNING、ERROR
            message: 日志文本
            payload: 附加结构化数据

        返回:
            已写入的日志记录。
        """
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "channel": channel,
            "level": level.upper(),
            "message": message,
            "payload": payload or {},
        }
        path = self.context.logs_dir / f"{channel}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _log_lock:
            with path.open("a", encoding="utf-8") as file_obj:
                file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def append_task_line(self, task_id: str, line: str, level: str = "INFO") -> dict:
        """写入任务日志（同时写 JSONL 和纯文本）。"""
        record = self.append("task", level, line, {"task_id": task_id})
        task_path = self.context.logs_dir / "tasks" / f"{task_id}.log"
        with _log_lock:
            with task_path.open("a", encoding="utf-8") as file_obj:
                file_obj.write(line + "\n")
        return record

    def read_channel(self, channel: str, limit: int = 500) -> list[dict]:
        """读取指定通道最近日志。"""
        path = self.context.logs_dir / f"{channel}.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records


def get_log_service() -> LogService:
    """获取日志服务单例。"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LogService()
    return _instance
