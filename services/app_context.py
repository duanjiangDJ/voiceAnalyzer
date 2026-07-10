"""
app_context.py — UI 运行上下文
=============================
集中管理项目根目录、资源目录、班级数据目录、日志目录和上传临时目录。

依赖:
    - dataclasses, pathlib（标准库）
    - src.config（项目内部模块）
"""

from dataclasses import dataclass
from pathlib import Path

from src.config import AppConfig


@dataclass(frozen=True)
class AppContext:
    """UI 运行上下文。"""

    base_dir: str
    standard_audio_dir: Path
    standard_text_dir: Path
    imitation_audio_dir: Path
    result_dir: Path
    knowledge_dir: Path
    classes_dir: Path
    logs_dir: Path
    uploads_dir: Path
    runtime_dir: Path


_app_context: AppContext | None = None


def get_app_context() -> AppContext:
    """
    获取 UI 运行上下文（模块级单例，避免重复读取 YAML 配置）。

    返回:
        AppContext 实例，包含关键目录的绝对路径。
    """
    global _app_context
    if _app_context is not None:
        return _app_context
    config = AppConfig.load()
    base_dir = Path(config.paths.base_dir)
    resource_dir = base_dir / "resource"
    classes_dir = resource_dir / "classes"
    logs_dir = resource_dir / "logs"
    uploads_dir = resource_dir / "uploads"
    runtime_dir = logs_dir / "runtime"
    classes_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (uploads_dir / "tmp").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "tasks").mkdir(parents=True, exist_ok=True)
    _app_context = AppContext(
        base_dir=str(base_dir),
        standard_audio_dir=base_dir / config.paths.standard_audio_dir,
        standard_text_dir=base_dir / config.paths.standard_text_dir,
        imitation_audio_dir=base_dir / config.paths.imitation_audio_dir,
        result_dir=base_dir / config.paths.result_dir,
        knowledge_dir=base_dir / config.paths.knowledge_dir,
        classes_dir=classes_dir,
        logs_dir=logs_dir,
        uploads_dir=uploads_dir,
        runtime_dir=runtime_dir,
    )
    return _app_context