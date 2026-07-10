"""
files.py — 素材管理 API
======================
提供标准文本、标准音频、学生音频和知识库文件的状态查询与基础写入能力。

依赖:
    - fastapi（第三方）
    - services.file_service（项目内部模块）
"""

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from services.class_service import DEFAULT_CLASS_ID, DEFAULT_UNIT_ID
from services.file_service import FileService


router = APIRouter(prefix="/files", tags=["files"])
_file_service = FileService()


class StandardTextPayload(BaseModel):
    """标准文本保存请求。"""

    content: str


@router.get("/status")
def get_file_status(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取素材准备状态。"""
    return {"success": True, "data": _file_service.get_status(class_id, unit_id)}


@router.get("/standard-text")
def get_standard_text(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """读取标准文本。"""
    return {"success": True, "data": _file_service.read_standard_text(class_id, unit_id)}


@router.put("/standard-text")
def save_standard_text(payload: StandardTextPayload, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """保存标准文本。"""
    return {"success": True, "data": _file_service.save_standard_text(payload.content, class_id, unit_id)}


@router.get("/student-audios")
def get_student_audios(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取学生音频列表。"""
    return {"success": True, "data": _file_service.list_student_audios(class_id, unit_id)}


@router.post("/student-audios")
async def upload_student_audios(files: list[UploadFile] = File(...), class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """统一上传学生音频或 zip 压缩包。"""
    return {"success": True, "data": await _file_service.save_student_uploads(files, class_id, unit_id)}


@router.post("/student-audios/zip")
async def upload_student_audio_zip(file: UploadFile = File(...), class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """上传包含学生音频的 zip 压缩包。"""
    return {"success": True, "data": await _file_service.save_student_audio_zip(file, class_id, unit_id)}


@router.post("/standard-audio")
async def upload_standard_audio(file: UploadFile = File(...), class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """上传或替换标准音频。"""
    return {"success": True, "data": await _file_service.save_standard_audio(file, class_id, unit_id)}


@router.get("/knowledge")
def get_knowledge() -> dict:
    """读取知识库预览。"""
    return {"success": True, "data": _file_service.read_knowledge_preview()}