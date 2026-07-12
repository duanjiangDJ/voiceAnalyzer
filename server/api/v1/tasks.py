"""
tasks.py — 任务控制 API
======================
提供评估任务启动、状态查询、取消和日志读取接口。

依赖:
    - fastapi（第三方）
    - services.pipeline_service（项目内部模块）
"""

from fastapi import APIRouter
from pydantic import BaseModel

from services.class_service import DEFAULT_CLASS_ID, DEFAULT_UNIT_ID
from services.pipeline_service import get_pipeline_service


router = APIRouter(prefix="/tasks", tags=["tasks"])
_pipeline_service = get_pipeline_service()


class TaskStartPayload(BaseModel):
    """任务启动请求。"""

    class_id: str = DEFAULT_CLASS_ID
    unit_id: str = DEFAULT_UNIT_ID


@router.post("")
def start_task(payload: TaskStartPayload | None = None) -> dict:
    """启动完整评估任务。"""
    payload = payload or TaskStartPayload()
    return {"success": True, "data": _pipeline_service.start_task(payload.class_id, payload.unit_id)}


@router.get("/current")
def get_current_task() -> dict:
    """获取当前任务快照。"""
    return {"success": True, "data": _pipeline_service.get_current_task()}


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    """取消运行中的任务。"""
    return {"success": True, "data": _pipeline_service.cancel_task(task_id)}


@router.get("/{task_id}/logs")
def get_task_logs(task_id: str) -> dict:
    """获取任务日志。"""
    return {"success": True, "data": _pipeline_service.get_logs(task_id)}