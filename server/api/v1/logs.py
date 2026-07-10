"""
logs.py — 日志查询 API
=====================
提供 API、任务和系统日志读取接口。

依赖:
    - fastapi（第三方）
    - services.log_service（项目内部模块）
"""

from fastapi import APIRouter

from services.log_service import get_log_service


router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/{channel}")
def get_logs(channel: str, limit: int = 500) -> dict:
    """读取指定通道最近日志。"""
    return {"success": True, "data": {"items": get_log_service().read_channel(channel, limit)}}