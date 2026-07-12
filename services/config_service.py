"""
config_service.py — UI 配置服务
==============================
读取和保存 resource/config.yaml 与 .env 中的可视化配置模型。

依赖:
    - dataclasses, os, pathlib（标准库）
    - yaml（第三方）
    - src.config（项目内部模块）
"""

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from services.app_context import get_app_context
from src.config import AppConfig


class ConfigService:
    """配置中心服务。"""

    def __init__(self) -> None:
        self.context = get_app_context()
        self.config_yaml = Path(self.context.base_dir) / "resource" / "config.yaml"
        self.dotenv_path = Path(self.context.base_dir) / ".env"

    def load_config(self) -> dict:
        """加载 UI 配置模型。"""
        config = AppConfig.load()
        data = asdict(config)
        actual_key = config.llm.api_key
        data["llm"]["api_key"] = "******" if actual_key else ""
        data["__actual_api_key"] = actual_key
        return data

    def validate_config(self, config_data: dict[str, Any]) -> dict:
        """校验配置模型的关键字段。"""
        errors = []
        llm = config_data.get("llm", {})
        modules = config_data.get("modules", {})
        if llm.get("max_concurrency", 1) < 1:
            errors.append({"field": "llm.max_concurrency", "message": "最大并发数必须大于 0"})
        if not any(bool(value) for value in modules.values()):
            errors.append({"field": "modules", "message": "至少需要启用一个模块"})
        return {"valid": not errors, "errors": errors}

    def save_config(self, config_data: dict[str, Any]) -> dict:
        """保存配置到 YAML，敏感值保留在 .env。"""
        validation = self.validate_config(config_data)
        if not validation["valid"]:
            return {"saved": False, "validation": validation}

        target_values = {
            **{f"llm.{k}": v for k, v in config_data.get("llm", {}).items() if k != "api_key"},
            **{f"whisper.{k}": v for k, v in config_data.get("whisper", {}).items()},
            **{f"modules.{k}": v for k, v in config_data.get("modules", {}).items()},
            **{f"wordcloud.{k}": v for k, v in config_data.get("wordcloud", {}).items()},
        }

        original = ""
        if self.config_yaml.exists():
            original = self.config_yaml.read_text(encoding="utf-8")

        updated = _apply_yaml_values(original, target_values)
        tmp_path = self.config_yaml.with_suffix(".yaml.tmp")
        tmp_path.write_text(updated, encoding="utf-8")
        tmp_path.replace(self.config_yaml)

        api_key = str(config_data.get("llm", {}).get("api_key", ""))
        if api_key and api_key != "******":
            self._set_env_value("LLM_API_KEY", api_key)
        return {"saved": True, "config": self.load_config()}

    def _set_env_value(self, key: str, value: str) -> None:
        """写入或更新 .env 中的指定键。"""
        lines = []
        if self.dotenv_path.exists():
            lines = self.dotenv_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for index, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[index] = f"{key}={value}"
                updated = True
        if not updated:
            lines.append(f"{key}={value}")
        os.replace(self._write_tmp_env(lines), self.dotenv_path)

    def _write_tmp_env(self, lines: list[str]) -> str:
        """写入 .env 临时文件。"""
        tmp_path = str(self.dotenv_path) + ".tmp"
        Path(tmp_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return tmp_path


def _apply_yaml_values(original: str, values: dict[str, Any]) -> str:
    """在原始 YAML 文本中替换指定键的值，保留注释和格式。"""
    import re

    result = original
    for dotted_key, new_value in values.items():
        *sections_raw, leaf_key = dotted_key.split(".")
        indent = "  " * len(sections_raw)
        value_str = _yaml_value_str(new_value, indent)
        # 匹配 "key: old_value" 行，old_value 可以是引号字符串或纯量
        # 要求行尾注释前至少有 2 个空格，避免把值内的 # 误判为注释
        pattern = re.compile(
            rf"^({re.escape(indent)}{re.escape(leaf_key)}:\s*)(.+?)(\s{{2,}}#.*)?$",
            re.MULTILINE,
        )
        result = pattern.sub(rf"\g<1>{value_str}\g<3>", result)
    return result


def _yaml_value_str(value: Any, indent: str) -> str:
    """将 Python 值转为 YAML 行内文本。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        if len(value) == 1 and isinstance(value[0], str):
            return f'"{value[0]}"'
        items = "\n".join(f"{indent}  - {_yaml_scalar(x)}" for x in value)
        return "\n" + items
    return f'"{value}"'


def _yaml_scalar(value: Any) -> str:
    """转为不带引号的 YAML 纯量。"""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return f"'{value}'"