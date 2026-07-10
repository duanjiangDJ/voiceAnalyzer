"""
results.py — 结果查询 API
========================
读取 summary、progress、学生报告和错误 JSON，转换为前端可消费的数据。

依赖:
    - fastapi（第三方）
    - services.result_service（项目内部模块）
"""

from fastapi import APIRouter

from services.class_service import DEFAULT_CLASS_ID, DEFAULT_UNIT_ID
from services.result_service import ResultService


router = APIRouter(prefix="/results", tags=["results"])
_result_service = ResultService()


@router.get("/summary")
def get_summary(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取成绩总表。"""
    return {"success": True, "data": _result_service.get_summary(class_id, unit_id)}


@router.get("/statistics")
def get_statistics(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取班级统计。"""
    return {"success": True, "data": _result_service.get_statistics(class_id, unit_id)}


@router.get("/students/{student_id}")
def get_student(student_id: str, class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取学生详情。"""
    return {"success": True, "data": _result_service.get_student_detail(student_id, class_id, unit_id)}


@router.get("/errors/aggregate")
def get_error_aggregate(class_id: str = DEFAULT_CLASS_ID, unit_id: str = DEFAULT_UNIT_ID) -> dict:
    """获取全班错误聚合。"""
    return {"success": True, "data": _result_service.get_error_aggregate(class_id, unit_id)}