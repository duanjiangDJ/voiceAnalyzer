"""
exports.py — 数据导出 API
========================
提供现有导出文件路径和可下载资源的发现接口。

依赖:
    - fastapi（第三方）
    - services.result_service（项目内部模块）
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from services.class_service import DEFAULT_CLASS_ID, DEFAULT_UNIT_ID
from services.result_service import ResultService


router = APIRouter(prefix="/exports", tags=["exports"])
_result_service = ResultService()


@router.get("/available")
def get_available_exports(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取当前可用的导出文件。"""
    return {"success": True, "data": _result_service.get_available_exports(class_id, unit_id)}


@router.get("/download")
def download_export(relative_path: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID):
    """下载指定班级/单元的导出文件。"""
    path = _result_service.resolve_export_path(relative_path, class_id, unit_id)
    if path is None:
        return {"success": False, "error": "导出文件不存在"}
    return FileResponse(path, filename=path.name)
