"""
config.py — 统一配置管理
=========================
优先级：.env（仅 API key）> resource/config.yaml > dataclass 默认值。

所有非敏感配置从 YAML 加载，敏感信息（LLM_API_KEY）从 .env 读取。
新增配置项时只需编辑 resource/config.yaml，无需修改此文件。

依赖:
    - os, dataclasses, typing, pathlib（标准库）
    - yaml（第三方，pyyaml）
    - dotenv（第三方，python-dotenv）
    - 零项目模块导入，无循环依赖风险
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ==============================================================================
# 子配置块
# ==============================================================================

@dataclass
class LLMConfig:
    """LLM API 连接与模型配置。"""
    api_key: str = ""
    """API 密钥（仅从 .env 读取，不写入 YAML）"""

    api_base: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-pro"
    thinking: bool = True
    max_concurrency: int = 400
    timeout: int = 120


@dataclass
class WhisperConfig:
    """Whisper 模型配置。"""
    model_name: str = "small.en"
    full_model_name: str = "medium.en"


@dataclass
class ModuleSwitches:
    """
    各模块启用开关。
    launcher 根据开关决定执行哪些步骤。
    """
    voice_analysis: bool = True
    whisper_transcribe: bool = True
    llm_compare: bool = True
    post_process: bool = True
    filter_precheck: bool = True
    error_visualize: bool = True


@dataclass
class WordCloudConfig:
    """词云生成参数（所有值可从 YAML 覆盖）。"""
    width: int = 800
    height: int = 600
    max_words: int = 100
    max_font_size: int | None = 120  # None=自动计算
    min_font_size: int = 8
    background_color: str = "white"
    prefer_horizontal: float = 1.0  # 1.0=全部横向
    color_all: str = "#455a64"       # 三合一图主色调
    stopwords: list[str] = field(default_factory=list)


@dataclass
class PathConfig:
    """
    路径配置。
    所有路径相对于 base_dir（项目根目录），在 AppConfig.load() 中自动计算。
    """
    base_dir: str = ""

    standard_audio_dir: str = "resource/standard_audio"
    standard_text_dir: str = "resource/standard_text"
    imitation_audio_dir: str = "resource/imitation_audio"
    result_dir: str = "resource/result"
    knowledge_dir: str = "resource/knowledge"
    history_dir: str = "resource/result/history"
    error_analysis_dir: str = "resource/result/error_analysis"

    def abs_path(self, relative: str) -> str:
        """将相对路径转为基于 base_dir 的绝对路径。"""
        return os.path.join(self.base_dir, relative)


# ==============================================================================
# 顶层 AppConfig — 唯一配置入口
# ==============================================================================

@dataclass
class AppConfig:
    """
    应用全局配置。

    使用方式:
        _config = AppConfig.load()
        _config.llm.model
        _config.wordcloud.stopwords
    """
    llm: LLMConfig = field(default_factory=LLMConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    modules: ModuleSwitches = field(default_factory=ModuleSwitches)
    wordcloud: WordCloudConfig = field(default_factory=WordCloudConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    # ==========================================================================
    # 工厂方法
    # ==========================================================================

    @classmethod
    def load(cls,
             config_yaml: str | None = None,
             dotenv_path: str | None = None,
             ) -> "AppConfig":
        """
        从 YAML 配置文件和 .env 加载所有配置。

        加载顺序（后加载的覆盖先加载的）：
          1. dataclass 默认值
          2. resource/config.yaml
          3. .env（仅 LLM_API_KEY）

        参数:
            config_yaml: YAML 配置文件路径，为 None 时自动搜索
            dotenv_path: .env 文件路径，为 None 时自动搜索

        返回:
            填充完整的 AppConfig 实例
        """
        # 1) 自动检测路径
        base_dir = _detect_base_dir()

        if config_yaml is None:
            config_yaml = os.path.join(base_dir, "resource", "config.yaml")
        if dotenv_path is None:
            dotenv_path = os.path.join(base_dir, ".env")

        # 2) 默认值
        cfg = cls(paths=PathConfig(base_dir=base_dir))

        # 3) 从 YAML 加载
        yaml_data = _load_yaml(config_yaml)
        if yaml_data:
            _apply_yaml(cfg, yaml_data)

        # 4) 从 .env 加载（仅 API key，覆盖 YAML 同级值）
        _load_dotenv(dotenv_path, cfg)

        return cfg


# ==============================================================================
# 内部辅助函数
# ==============================================================================

def _detect_base_dir() -> str:
    """自动检测项目根目录。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_yaml(path: str) -> dict | None:
    """
    加载 YAML 配置文件。

    返回:
        解析后的字典，文件不存在或解析失败时返回 None
    """
    if not os.path.exists(path):
        print(f"[配置] YAML 文件不存在: {path}，使用默认值。")
        return None
    try:
        import yaml
    except ImportError:
        print("[配置] pyyaml 未安装，跳过 YAML 加载。")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            print(f"[配置] YAML 格式异常，使用默认值。")
            return None
        print(f"[配置] 已加载: {path}")
        return data
    except Exception as e:
        print(f"[配置] YAML 加载失败: {e}，使用默认值。")
        return None


def _apply_yaml(cfg: AppConfig, data: dict) -> None:
    """
    将 YAML 字典逐层应用到 AppConfig。

    支持的键：
      - llm: api_base, model, thinking, max_concurrency, timeout
      - whisper: model_name, full_model_name
      - modules: voice_analysis, whisper_transcribe, llm_compare,
                 post_process, filter_precheck, error_visualize
      - wordcloud: width, height, max_words, background_color,
                   prefer_horizontal, color_all, stopwords
    """
    # --- llm ---
    llm_data = data.get("llm")
    if isinstance(llm_data, dict):
        for key in ("api_base", "model", "thinking", "max_concurrency", "timeout"):
            if key in llm_data:
                val = llm_data[key]
                # YAML 的 true/false 字符串 → Python bool
                if key == "thinking" and isinstance(val, str):
                    val = val.lower() in ("true", "1", "yes")
                setattr(cfg.llm, key, val)

    # --- whisper ---
    whisper_data = data.get("whisper")
    if isinstance(whisper_data, dict):
        for key in ("model_name", "full_model_name"):
            if key in whisper_data:
                setattr(cfg.whisper, key, whisper_data[key])

    # --- modules ---
    modules_data = data.get("modules")
    if isinstance(modules_data, dict):
        for key in ("voice_analysis", "whisper_transcribe", "llm_compare",
                     "post_process", "filter_precheck", "error_visualize"):
            if key in modules_data:
                val = modules_data[key]
                if isinstance(val, str):
                    val = val.lower() in ("true", "1", "yes")
                setattr(cfg.modules, key, val)

    # --- wordcloud ---
    wc_data = data.get("wordcloud")
    if isinstance(wc_data, dict):
        for key in ("width", "height", "max_words", "max_font_size",
                     "min_font_size", "background_color",
                     "prefer_horizontal", "color_all"):
            if key in wc_data:
                setattr(cfg.wordcloud, key, wc_data[key])
        if "stopwords" in wc_data:
            cfg.wordcloud.stopwords = [str(w).strip().lower()
                                       for w in wc_data["stopwords"]
                                       if str(w).strip()]


def _load_dotenv(dotenv_path: str, cfg: AppConfig) -> None:
    """
    从 .env 加载敏感配置（仅 LLM_API_KEY）。

    .env 的值优先级最高，直接覆盖 YAML 中同名字段。
    """
    # 尝试通过 python-dotenv 加载
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path)
    except ImportError:
        pass

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if api_key:
        cfg.llm.api_key = api_key

    # 如果 .env 中也设置了其他变量（旧格式兼容），同样加载
    for env_key, attr in [
        ("LLM_API_BASE", "api_base"),
        ("LLM_MODEL", "model"),
        ("LLM_MAX_CONCURRENCY", "max_concurrency"),
        ("LLM_TIMEOUT", "timeout"),
    ]:
        val = os.environ.get(env_key, "").strip()
        if val:
            if attr in ("max_concurrency", "timeout"):
                setattr(cfg.llm, attr, int(val) if val.isdigit() else getattr(cfg.llm, attr))
            else:
                setattr(cfg.llm, attr, val)

    for env_key, attr in [
        ("LLM_THINKING", "thinking"),
    ]:
        val = os.environ.get(env_key, "").strip().lower()
        if val:
            cfg.llm.thinking = val in ("1", "true", "yes", "enabled")

    for env_key, attr in [
        ("WHISPER_MODEL", "model_name"),
        ("WHISPER_FULL_MODEL", "full_model_name"),
    ]:
        val = os.environ.get(env_key, "").strip()
        if val:
            setattr(cfg.whisper, attr, val)

    # 模块开关（从 .env 读取，覆盖 YAML）
    for env_key, attr in [
        ("FILTER_PRECHECK", "filter_precheck"),
        ("VOICE_ANALYSIS", "voice_analysis"),
        ("WHISPER_TRANSCRIBE", "whisper_transcribe"),
        ("LLM_COMPARE", "llm_compare"),
        ("POST_PROCESS", "post_process"),
        ("ERROR_VISUALIZE", "error_visualize"),
    ]:
        val = os.environ.get(env_key, "").strip()
        if val:
            setattr(cfg.modules, attr, val in ("1", "true", "yes", "enabled"))
