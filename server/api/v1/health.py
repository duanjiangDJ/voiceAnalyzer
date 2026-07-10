"""
health.py — 健康检查 API
========================
提供服务状态、关键目录和主要依赖检测。

依赖:
    - importlib.util（标准库）
    - fastapi（第三方）
    - services.app_context（项目内部模块）
"""

import importlib.util

from fastapi import APIRouter

from services.app_context import get_app_context


router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def get_health() -> dict:
    """
    获取基础服务状态。

    返回:
        包含服务状态和项目根目录的字典。
    """
    context = get_app_context()
    return {"success": True, "data": {"status": "ok", "base_dir": context.base_dir}}


@router.get("/dependencies")
def get_dependencies() -> dict:
    """
    获取主要依赖和目录状态。

    返回:
        依赖名称到可用状态的映射。
    """
    context = get_app_context()
    dependencies = {
        "fastapi": importlib.util.find_spec("fastapi") is not None,
        "opensmile": importlib.util.find_spec("opensmile") is not None,
        "whisper": importlib.util.find_spec("whisper") is not None,
        "pandas": importlib.util.find_spec("pandas") is not None,
    }
    directories = {
        "standard_audio": context.standard_audio_dir.exists(),
        "standard_text": context.standard_text_dir.exists(),
        "imitation_audio": context.imitation_audio_dir.exists(),
        "result": context.result_dir.exists(),
        "knowledge": context.knowledge_dir.exists(),
    }
    return {"success": True, "data": {"dependencies": dependencies, "directories": directories}}