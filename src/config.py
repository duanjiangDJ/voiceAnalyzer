"""
config.py — 统一配置管理
=========================
使用 Python dataclass 集中管理所有模块的配置参数，从 .env 文件加载。
所有模块通过本模块获取配置，不再分散读取环境变量。

依赖:
    - os, dataclasses（标准库）
    - 零项目模块导入，无循环依赖风险
"""

import os
from dataclasses import dataclass, field


# ==============================================================================
# 子配置块
# ==============================================================================

@dataclass
class LLMConfig:
    """LLM API 连接与模型配置。"""
    api_key: str = ""
    """API 密钥（Bearer Token）"""

    api_base: str = "https://api.deepseek.com/v1"
    """API 基础地址（OpenAI 兼容格式，自动拼接 /chat/completions）"""

    model: str = "deepseek-v4-pro"
    """模型名称"""

    thinking: bool = True
    """是否启用 DeepSeek 思考模式"""

    max_concurrency: int = 400
    """LLM 线程池最大并发数（纯网络 I/O）"""

    timeout: int = 120
    """API 请求超时秒数"""


@dataclass
class ModuleSwitches:
    """
    各模块启用开关。
    launcher 根据开关决定执行哪些步骤，关闭时自动跳过对应阶段。
    值含义: True = 启用, False = 跳过。
    """
    filter_precheck: bool = True
    """预检查：对比音频文件列表与已有结果"""

    voice_analysis: bool = True
    """OpenSMILE 语音特征分析"""

    whisper_transcribe: bool = True
    """Whisper 语音转写"""

    llm_compare: bool = True
    """LLM 文本比对"""

    post_process: bool = True
    """后处理：生成汇总 Excel"""

    error_visualize: bool = True
    """错题可视化：词云 + 历史曲线"""


@dataclass
class WhisperConfig:
    """Whisper 模型配置。"""
    model_name: str = "small.en"
    """默认 Whisper 模型名称（transcribe_only 使用）"""

    full_model_name: str = "medium.en"
    """完整 Whisper 模型名称（独立运行 main() 使用）"""


@dataclass
class PathConfig:
    """
    路径配置。
    所有路径相对于 base_dir（项目根目录），在 AppConfig.load() 中自动计算。
    """
    base_dir: str = ""
    """项目根目录绝对路径（运行时自动检测）"""

    standard_audio_dir: str = "resource/standard_audio"
    """标准朗读音频目录"""

    standard_text_dir: str = "resource/standard_text"
    """标准文本目录"""

    imitation_audio_dir: str = "resource/imitation_audio"
    """学生仿读音频目录"""

    result_dir: str = "resource/result"
    """输出结果目录"""

    knowledge_dir: str = "resource/knowledge"
    """知识库目录"""

    history_dir: str = "resource/result/history"
    """历史运行归档目录"""

    error_analysis_dir: str = "resource/result/error_analysis"
    """错题可视化输出目录"""

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
        _config = AppConfig.load()  # 从 .env 加载
        _config.llm.model           # 访问 LLM 模型名
        _config.modules.voice_analysis  # 检查语音分析开关
        _config.paths.abs_path("resource/result")  # 获取绝对路径
    """
    llm: LLMConfig = field(default_factory=LLMConfig)
    modules: ModuleSwitches = field(default_factory=ModuleSwitches)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    # ==========================================================================
    # 工厂方法
    # ==========================================================================

    @classmethod
    def load(cls, dotenv_path: str | None = None) -> "AppConfig":
        """
        从 .env 文件加载所有配置，未设置的键使用默认值。

        参数:
            dotenv_path: .env 文件路径，为 None 时自动搜索项目根目录

        返回:
            填充完整的 AppConfig 实例
        """
        # 1) 尝试加载 .env 文件（通过 python-dotenv）
        _try_load_dotenv(dotenv_path)

        # 2) 自动检测 base_dir
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 3) 从环境变量读取各字段
        llm = LLMConfig(
            api_key=os.environ.get("LLM_API_KEY", ""),
            api_base=os.environ.get("LLM_API_BASE", "https://api.deepseek.com/v1"),
            model=os.environ.get("LLM_MODEL", "deepseek-v4-pro"),
            thinking=_env_bool("LLM_THINKING", True),
            max_concurrency=int(os.environ.get("LLM_MAX_CONCURRENCY", "400")),
            timeout=int(os.environ.get("LLM_TIMEOUT", "120")),
        )

        modules = ModuleSwitches(
            filter_precheck=_env_bool("FILTER_PRECHECK", True),
            voice_analysis=_env_bool("VOICE_ANALYSIS", True),
            whisper_transcribe=_env_bool("WHISPER_TRANSCRIBE", True),
            llm_compare=_env_bool("LLM_COMPARE", True),
            post_process=_env_bool("POST_PROCESS", True),
            error_visualize=_env_bool("ERROR_VISUALIZE", True),
        )

        whisper = WhisperConfig(
            model_name=os.environ.get("WHISPER_MODEL", "small.en"),
            full_model_name=os.environ.get("WHISPER_FULL_MODEL", "medium.en"),
        )

        paths = PathConfig(base_dir=base_dir)

        return cls(llm=llm, modules=modules, whisper=whisper, paths=paths)


# ==============================================================================
# 内部辅助函数
# ==============================================================================

def _env_bool(key: str, default: bool) -> bool:
    """读取环境变量的布尔值（支持 1/true/yes/enabled 和 0/false/no/disabled）。"""
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "enabled")


def _try_load_dotenv(dotenv_path: str | None) -> None:
    """尝试加载 .env 文件，dotenv 未安装或文件不存在时静默跳过。"""
    if dotenv_path is None:
        dotenv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env",
        )
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path)
    except ImportError:
        pass
