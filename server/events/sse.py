"""
sse.py — 任务事件流
==================
通过 SSE 向前端推送当前任务快照和日志更新。
使用 asyncio.Queue 实现事件驱动推送（替代轮询）。

依赖:
    - asyncio, json（标准库）
    - fastapi（第三方）
    - services.pipeline_service（项目内部模块）
"""

import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from services.pipeline_service import get_pipeline_service


router = APIRouter(prefix="/events", tags=["events"])
_pipeline_service = get_pipeline_service()


@router.get("/tasks/{task_id}")
async def subscribe_task(task_id: str) -> StreamingResponse:
    """订阅任务事件（事件驱动推送 + 心跳保活）。"""
    queue = _pipeline_service.get_queue(task_id)
    # 注入事件循环引用，使后台线程能安全推送
    loop = asyncio.get_running_loop()
    _pipeline_service.set_task_loop(task_id, loop)

    async def event_generator():
        last_ping = time.monotonic()
        # 先发送当前快照
        snapshot = _pipeline_service.get_task(task_id)
        if snapshot:
            logs = _pipeline_service.get_logs(task_id)
            yield f"event: task\ndata: {json.dumps({'snapshot': snapshot, 'logs': logs}, ensure_ascii=False)}\n\n"

        if queue is None:
            yield f"event: task\ndata: {json.dumps({'snapshot': {'status': 'not_found', 'logs': []}, 'logs': []}, ensure_ascii=False)}\n\n"
            return

        last_log_size = len(_pipeline_service.get_logs(task_id))
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.5)
            except asyncio.TimeoutError:
                # 每 15s 发送心跳保持连接
                now = time.monotonic()
                if now - last_ping >= 15:
                    last_ping = now
                    yield ": ping\n\n"
                # 检查增量日志
                current_logs = _pipeline_service.get_logs(task_id)
                new_logs = current_logs[last_log_size:]
                if new_logs:
                    last_log_size = len(current_logs)
                    snapshot = _pipeline_service.get_task(task_id)
                    yield f"event: task\ndata: {json.dumps({'snapshot': snapshot or {}, 'logs': new_logs}, ensure_ascii=False)}\n\n"
                continue

            current_logs = _pipeline_service.get_logs(task_id)
            new_logs = current_logs[last_log_size:]
            last_log_size = len(current_logs)
            snapshot = _pipeline_service.get_task(task_id) or {}
            yield f"event: task\ndata: {json.dumps({'snapshot': snapshot, 'logs': new_logs}, ensure_ascii=False)}\n\n"

            status = snapshot.get("status", "")
            if status in {"completed", "failed", "cancelled", "not_found"}:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
