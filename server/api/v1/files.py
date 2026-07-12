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


# ---------- 音频管理 ----------

@router.get("/student-audio-status")
def get_student_audio_status(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取班级学生的音频提交状态（含提交时间）。"""
    return {"success": True, "data": _file_service.list_student_audio_status(class_id, unit_id)}


@router.post("/student-audio/single")
async def upload_single_student_audio(file: UploadFile = File(...), student_name: str = "", student_id: str = "",
                                      class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """上传单个学生音频。"""
    return {"success": True, "data": await _file_service.save_single_student_audio(file, student_name, student_id, class_id, unit_id)}


@router.post("/student-audio/batch")
async def upload_batch_student_audio(files: list[UploadFile] = File(...), names: str = "", ids: str = "",
                                     class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """批量上传学生音频，names/ids 为逗号分隔的姓名/学号列表（与 files 一一对应）。"""
    name_list = [n.strip() for n in names.split(",")] if names else []
    id_list = [i.strip() for i in ids.split(",")] if ids else []
    saved = []
    failed = []
    for idx, upload in enumerate(files):
        sname = name_list[idx] if idx < len(name_list) else ""
        sid = id_list[idx] if idx < len(id_list) else ""
        result = await _file_service.save_single_student_audio(upload, sname, sid, class_id, unit_id)
        if result.get("saved"):
            saved.append(result.get("filename", ""))
        else:
            failed.append({"filename": Path(upload.filename or "").name, "reason": result.get("reason", "")})
    _file_service.class_service.upsert_students_from_audio(class_id, unit_id)
    return {"success": True, "data": {"saved": saved, "failed": failed}}


@router.delete("/student-audio/{filename}")
def delete_student_audio(filename: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """删除指定学生音频文件。"""
    return {"success": True, "data": _file_service.delete_student_audio(filename, class_id, unit_id)}


@router.delete("/student-result/{student_key}")
def delete_student_result(student_key: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """删除指定学生在当前单元的评分结果。"""
    return {"success": True, "data": _file_service.delete_student_result(student_key, class_id, unit_id)}