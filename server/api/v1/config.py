"""
config.py — 配置中心 API
=======================
提供项目配置读取、保存和默认恢复能力。

依赖:
    - fastapi, pydantic（第三方）
    - services.config_service（项目内部模块）
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from services.config_service import ConfigService


router = APIRouter(prefix="/config", tags=["config"])
_config_service = ConfigService()


class ConfigPayload(BaseModel):
    """配置保存请求。"""

    config: dict[str, Any]


@router.get("")
def get_config() -> dict:
    """获取 UI 配置模型。"""
    return {"success": True, "data": _config_service.load_config()}


@router.put("")
def save_config(payload: ConfigPayload) -> dict:
    """保存 UI 配置模型。"""
    return {"success": True, "data": _config_service.save_config(payload.config)}


@router.post("/validate")
def validate_config(payload: ConfigPayload) -> dict:
    """校验配置模型。"""
    return {"success": True, "data": _config_service.validate_config(payload.config)}