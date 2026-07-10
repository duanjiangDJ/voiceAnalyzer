"""
deps.py — FastAPI 依赖注入
=========================
通过 Depends 向所有路由提供统一服务实例。

依赖:
    - services.app_context, services.pipeline_service, services.log_service
"""

from services.class_service import ClassService
from services.config_service import ConfigService
from services.file_service import FileService
from services.log_service import get_log_service
from services.pipeline_service import get_pipeline_service
from services.result_service import ResultService


def get_classes():
    return ClassService()


def get_config():
    return ConfigService()


def get_files():
    return FileService()


def get_pipeline():
    return get_pipeline_service()


def get_results():
    return ResultService()


def get_logs():
    return get_log_service()
