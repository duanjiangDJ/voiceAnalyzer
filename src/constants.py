"""
constants.py — 共享常量与正则表达式
====================================
集中管理全项目共用的 Markdown 标记、音频扩展名、评分维度、
OpenSMILE 特征列名和正则模式，避免跨文件重复定义导致不一致。

所有常量使用 Final 标注，零项目模块导入，任何模块均可安全引用。
"""

import re
from typing import Final

# ==============================================================================
# Markdown 报告节标题 — 写入和读取共享同一标记
# ==============================================================================
MD_TRANSCRIBE_HEADER: Final[str] = "**=== 转写文本 ===**"
"""转写文本节标题"""

MD_STANDARD_HEADER: Final[str] = "**=== 标准文本 ===**"
"""标准文本节标题"""

MD_COMPARE_HEADER_PREFIX: Final[str] = "**=== LLM 比对结果（模型: "
"""比对结果节标题前缀（后接模型名 + ）===**）"""


def _build_md_compare_header(model_name: str) -> str:
    """构建完整的比对结果节标题。"""
    return f"{MD_COMPARE_HEADER_PREFIX}{model_name}）===**"


# ---- 从 MD 报告提取各节的预编译正则（供 audio_output 等读取用） ----
_RE_TRANSCRIBE = re.escape(MD_TRANSCRIBE_HEADER)
_RE_STANDARD = re.escape(MD_STANDARD_HEADER)
_RE_COMPARE_PREFIX = re.escape(MD_COMPARE_HEADER_PREFIX)

MD_PATTERN_TRANSCRIBE: Final[re.Pattern] = re.compile(
    _RE_TRANSCRIBE + r"\n(.*?)\n\n" + _RE_STANDARD, re.DOTALL
)
"""正则：提取转写文本部分（位于 **=== 转写文本 ===** 和 **=== 标准文本 ===** 之间）"""

MD_PATTERN_STANDARD: Final[re.Pattern] = re.compile(
    _RE_STANDARD + r"\n(.*?)\n\n" + _RE_COMPARE_PREFIX, re.DOTALL
)
"""正则：提取标准文本部分（位于 **=== 标准文本 ===** 和比对结果之间）"""

MD_PATTERN_COMPARE: Final[re.Pattern] = re.compile(
    _RE_COMPARE_PREFIX + r".*?）===\*\*\n(.*)", re.DOTALL
)
"""正则：提取比对结果部分（从 **=== LLM 比对结果...===** 之后到文末）"""

# ==============================================================================
# 音频文件扩展名 — 两种形式（供 glob 和 endswith 分别使用）
# ==============================================================================
AUDIO_EXTENSIONS: Final[tuple[str, ...]] = (
    "mp3", "wav", "m4a", "flac", "ogg", "mp4",
)
"""裸扩展名（供 glob.glob 使用）"""

AUDIO_EXTENSIONS_DOT: Final[tuple[str, ...]] = tuple(
    f".{e}" for e in AUDIO_EXTENSIONS
)
"""带点的扩展名（供 str.endswith 使用）"""

# ==============================================================================
# 评分维度与 CSV 列定义
# ==============================================================================
VOICE_KEYS: Final[list[str]] = [
    "基频均值", "基频标准差", "能量均值", "Jitter均值",
    "Shimmer均值", "log HNR均值", "谱质心均值", "语速", "语音综合分",
]
"""语音分析 8 个评分维度 + 综合分"""

SCORE_COLS: Final[list[str]] = VOICE_KEYS + ["总成绩"]
"""summary.csv 中所有评分列"""

SUMMARY_COLUMNS: Final[list[str]] = ["学生", "单词准确率"] + SCORE_COLS
"""summary.csv 完整列定义"""

# ==============================================================================
# OpenSMILE 特征列关键词 — 用于从 DataFrame 列名中定位目标列
# ==============================================================================
OS_KEYWORDS: Final[list[str]] = [
    "F0final",
    "voicingFinal",
    "RMSenergy",
    "spectralCentroid",
    "jitterLocal",
    "shimmerLocal",
    "logHNR",
]
"""
OpenSMILE ComParE 2016 LLD 特征列匹配关键词列表。
顺序: F0, voicing, energy, spectral_centroid, jitter, shimmer, HNR
"""

# ==============================================================================
# 学生信息提取正则
# ==============================================================================
STUDENT_ID_PATTERN: Final[re.Pattern] = re.compile(r"\d{10}")
"""10 位学号正则（从文件名或文件夹名中提取）"""

# ==============================================================================
# 文字比对错误类型标记
# ==============================================================================
ERROR_TYPE_REPLACE: Final[str] = "replace"
"""替换错误：读错的词"""

ERROR_TYPE_INSERT: Final[str] = "insert"
"""多读错误：多读的词"""

ERROR_TYPE_DELETE: Final[str] = "delete"
"""漏读错误：遗漏的词"""

ERROR_CATEGORIES: Final[list[str]] = [ERROR_TYPE_REPLACE, ERROR_TYPE_INSERT, ERROR_TYPE_DELETE]
"""所有错误类型列表"""

# ==============================================================================
# 词云颜色方案 — 按错误类型区分
# ==============================================================================
WORDCLOUD_COLORS: Final[dict[str, str]] = {
    ERROR_TYPE_REPLACE: "#d32f2f",   # 红色系 — 替换错误
    ERROR_TYPE_INSERT: "#1976d2",    # 蓝色系 — 多读错误
    ERROR_TYPE_DELETE: "#616161",    # 灰色系 — 漏读错误
}
"""词云图配色：按错误类型使用不同色调"""
