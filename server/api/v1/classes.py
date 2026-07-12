"""
classes.py — 班级与单元管理 API
==============================
提供班级、单元、学生名单和当前上下文查询接口。

依赖:
    - fastapi, pydantic（第三方）
    - services.class_service（项目内部模块）
"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from services.class_service import ClassService, DEFAULT_CLASS_ID, DEFAULT_UNIT_ID


router = APIRouter(prefix="/classes", tags=["classes"])
_class_service = ClassService()


class NamedPayload(BaseModel):
    """创建班级或单元请求。"""

    name: str
    description: str = ""


class StudentPayload(BaseModel):
    """学生名单保存请求。"""

    name: str
    student_id: str
    status: str = "active"
    note: str = ""


@router.get("")
def list_classes() -> dict:
    """列出所有班级。"""
    return {"success": True, "data": _class_service.list_classes()}


@router.post("")
def create_class(payload: NamedPayload) -> dict:
    """创建班级。"""
    return {"success": True, "data": _class_service.create_class(payload.name, payload.description)}


@router.put("/{class_id}")
def update_class(class_id: str, payload: NamedPayload) -> dict:
    """更新班级。"""
    return {"success": True, "data": _class_service.update_class(class_id, payload.name, payload.description)}


@router.delete("/{class_id}")
def archive_class(class_id: str) -> dict:
    """归档班级。"""
    return {"success": True, "data": _class_service.archive_class(class_id)}


@router.delete("/{class_id}/permanent")
def permanently_delete_class(class_id: str) -> dict:
    """物理删除班级及所有数据。"""
    return {"success": True, "data": _class_service.permanently_delete_class(class_id)}


@router.get("/{class_id}/units")
def list_units(class_id: str) -> dict:
    """列出所有共享单元（class_id 保留兼容性）。"""
    return {"success": True, "data": _class_service.list_units(class_id)}


@router.post("/{class_id}/units")
def create_unit(class_id: str, payload: NamedPayload) -> dict:
    """创建共享单元（class_id 保留兼容性）。"""
    return {"success": True, "data": _class_service.create_unit(class_id, payload.name, payload.description)}


@router.put("/{class_id}/units/{unit_id}")
def update_unit(class_id: str, unit_id: str, payload: NamedPayload) -> dict:
    """更新指定班级的单元。"""
    return {"success": True, "data": _class_service.update_unit(class_id, unit_id, payload.name, payload.description)}


@router.delete("/{class_id}/units/{unit_id}")
def archive_unit(class_id: str, unit_id: str) -> dict:
    """归档指定班级的单元。"""
    return {"success": True, "data": _class_service.archive_unit(class_id, unit_id)}


@router.delete("/{class_id}/units/{unit_id}/permanent")
def permanently_delete_unit(class_id: str, unit_id: str) -> dict:
    """物理删除单元及所有班级中该单元的所有数据。"""
    return {"success": True, "data": _class_service.permanently_delete_unit(class_id, unit_id)}


@router.get("/{class_id}/students")
def list_students(class_id: str, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """列出指定班级学生及单元提交状态。"""
    return {"success": True, "data": _class_service.list_students(class_id, unit_id)}


@router.post("/{class_id}/students")
def upsert_student(class_id: str, payload: StudentPayload) -> dict:
    """新增或更新学生名单。"""
    return {"success": True, "data": _class_service.upsert_student(class_id, payload.model_dump())}


@router.delete("/{class_id}/students/{student_id}")
def delete_student(class_id: str, student_id: str) -> dict:
    """归档学生名单记录（不删除音频和结果）。"""
    return {"success": True, "data": _class_service.delete_student(class_id, student_id)}


@router.delete("/{class_id}/students/{student_id}/permanent")
def permanently_delete_student(class_id: str, student_id: str) -> dict:
    """物理删除学生名单、音频和结果。"""
    return {"success": True, "data": _class_service.permanently_delete_student(class_id, student_id)}


@router.post("/{class_id}/students/import-csv")
async def import_students_csv(class_id: str, file: UploadFile = File(...)) -> dict:
    """导入学生名单 CSV。"""
    content = (await file.read()).decode("utf-8-sig")
    return {"success": True, "data": _class_service.import_students_csv(class_id, content)}


@router.post("/{class_id}/units/{unit_id}/sync-students")
def sync_students(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """从单元音频文件同步学生名单。"""
    return {"success": True, "data": _class_service.upsert_students_from_audio(class_id, unit_id)}


@router.get("/students/template")
def download_student_csv_template():
    """下载学生名单 CSV 模板（UTF-8 BOM，Excel 兼容）。"""
    csv_content = "\ufeff姓名,学号\n张三,2024000001\n"
    return Response(
        content=csv_content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=student_template.csv"},
    )