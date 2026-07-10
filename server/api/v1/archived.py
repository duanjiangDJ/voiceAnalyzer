"""
archived.py — 归档项目管理 API
=============================
列出、复原、物理删除归档项目。

依赖:
    - fastapi（第三方）
    - services.class_service（项目内部模块）
"""

from fastapi import APIRouter

from services.class_service import ClassService


router = APIRouter(prefix="/archived", tags=["archived"])
_class_service = ClassService()


@router.get("")
def list_archived() -> dict:
    """列出所有归档项目。"""
    return {"success": True, "data": {"items": _class_service.get_archived_items()}}


@router.post("/{record_id}/restore")
def restore_archived(record_id: str) -> dict:
    """复原归档项目。"""
    return {"success": True, "data": _class_service.restore_archived_item(record_id)}


@router.delete("/{record_id}")
def permanently_delete_archived(record_id: str) -> dict:
    """物理删除归档项目。"""
    return {"success": True, "data": _class_service.permanently_delete_archived_item(record_id)}
