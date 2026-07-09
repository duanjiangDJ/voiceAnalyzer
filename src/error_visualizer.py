"""
error_visualizer.py — 错题可视化：词云 + 历史进步曲线
======================================================
对学生文本比对中的错误进行聚合分析和可视化展示。

功能:
    1. 错题词云：4 张图（替换/多读/漏读 + 三合一合计），
       spaCy 词性还原（可选）、停用词过滤、按频次彩色渲染
    2. CSV 导出：每种错误类型导出词频 CSV，支持 pandas 汇总
    3. 历史进步曲线：每位学生一张独立折线图，展示历次运行趋势
    4. 结果归档：每次运行写入 history/ 并附带 meta.json

公共 API:
    generate_error_wordclouds()  — 生成 4 张词云图 + CSV
    generate_progress_curves()   — 生成每位学生的历史曲线
    archive_current_result()     — 归档本次运行结果（含 meta.json）
    lemmatize_word()             — spaCy 词性还原（供外部调用）

数据来源:
    - 词云: 每位学生的 _errors.json（由 text_llm.py 生成）
    - 曲线: resource/result/history/ 下归档的 summary.csv

依赖:
    - matplotlib, pandas, numpy (第三方)
    - wordcloud (第三方，需单独安装)
    - spacy (可选，用于词性还原)
    - src.config: AppConfig (词云参数 + 停用词)
    - src.utils: ensure_dir, read_errors_json
    - src.constants: ERROR_TYPE_REPLACE, ERROR_TYPE_INSERT, ERROR_TYPE_DELETE, WORDCLOUD_COLORS
"""

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 path（支持独立运行）
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")  # 多线程安全，必须在 import pyplot 之前
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# ---- 中文字体设置 ----
for _font_name in ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei",
                     "Noto Sans CJK SC", "DejaVu Sans"]:
    try:
        _test_fonts = [f.name for f in fm.fontManager.ttflist]
        if _font_name in _test_fonts:
            plt.rcParams["font.sans-serif"] = [_font_name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            break
    except Exception:
        continue

import numpy as np
import pandas as pd

from src.config import AppConfig
from src.constants import (
    ERROR_CATEGORIES,
    ERROR_TYPE_DELETE,
    ERROR_TYPE_INSERT,
    ERROR_TYPE_REPLACE,
)
from src.utils import ensure_dir, read_errors_json

# 模块级配置
_config = AppConfig.load()


# ==============================================================================
# spaCy 词性还原 — 懒加载 + 自动下载
# ==============================================================================

_nlp = None
"""spaCy 模型缓存：None=未初始化，spaCy模型实例=已加载，False=加载失败"""


def get_spacy_nlp():
    """
    懒加载 spaCy 英文模型 en_core_web_sm。

    首次调用时自动检测并加载模型；若模型未安装则尝试自动下载。
    加载失败时返回 None，调用方应降级为原词统计。

    返回:
        spaCy Language 对象，或 None（加载失败时）
    """
    global _nlp
    if _nlp is not None:
        return _nlp if _nlp is not False else None

    try:
        import spacy
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("[词云] 正在下载 spaCy 英文模型 (en_core_web_sm) ...")
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                check=True,
            )
            _nlp = spacy.load("en_core_web_sm")
        print("[词云] spaCy 模型加载成功")
    except ImportError:
        print("[词云] ⚠️  spaCy 未安装，将跳过词性还原。"
              "安装方法: pip install spacy && python -m spacy download en_core_web_sm")
        _nlp = False
    except Exception as e:
        print(f"[词云] ⚠️  spaCy 加载失败: {e}，将跳过词性还原")
        _nlp = False

    return _nlp if _nlp is not False else None


def lemmatize_word(word: str) -> str:
    """
    对单个单词进行词性还原（running→run, cats→cat, studied→study）。

    对代词、限定词、介词、连词等虚词保留原形，避免过度还原。
    spaCy 不可用时降级为小写转换。

    参数:
        word: 原始单词

    返回:
        还原后的词元（小写），或原词小写（spaCy 不可用时）
    """
    if not word or len(word) < 2:
        return word.lower() if word else word

    nlp = get_spacy_nlp()
    if nlp is None:
        return word.lower()

    try:
        doc = nlp(word)
        if doc and len(doc) > 0:
            lemma = doc[0].lemma_
            # 虚词保留原形，避免过度还原
            if doc[0].pos_ in ("PRON", "DET", "ADP", "CONJ", "SCONJ", "PART"):
                return word.lower()
            return lemma.lower() if lemma else word.lower()
    except Exception:
        pass
    return word.lower()


# ==============================================================================
# 停用词加载 — 支持文件路径和 YAML 列表两种模式
# ==============================================================================

def load_stopwords_from_file(config, project_root: Path | None = None) -> set:
    """
    加载停用词集合。

    支持两种模式：
      - YAML 列表：config.wordcloud.stopwords 为 list[str]，直接解析
      - 文件路径：config.wordcloud.stopwords 为 str，从该文件逐行读取（支持 # 注释）

    同时合并 wordcloud 库内置的 STOPWORDS（如果可用）。

    参数:
        config:       AppConfig 实例
        project_root: 项目根目录（用于解析相对路径），为 None 时自动检测

    返回:
        停用词集合（全部小写）
    """
    try:
        from wordcloud import STOPWORDS
        default_stopwords = set(STOPWORDS)
    except ImportError:
        default_stopwords = set()

    if project_root is None:
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent

    stopwords_source = config.wordcloud.stopwords

    if isinstance(stopwords_source, str):
        # 文件路径模式
        stopwords_path = project_root / stopwords_source
        custom_stopwords = set()
        try:
            if stopwords_path.exists():
                with open(stopwords_path, "r", encoding="utf-8") as f:
                    for line in f:
                        word = line.strip().lower()
                        if word and not word.startswith("#"):
                            custom_stopwords.add(word)
                print(f"[词云] 从文件加载 {len(custom_stopwords)} 个停用词: {stopwords_path}")
        except Exception as e:
            print(f"[词云] ⚠️  停用词文件加载失败: {e}")
        return default_stopwords | custom_stopwords
    else:
        # YAML 列表模式
        return set(w.lower() for w in stopwords_source) | default_stopwords


# ==============================================================================
# 错误词提取 — 从 _errors.json 中提取真实错误单词
# ==============================================================================

def extract_error_words_from_json(errors_data: dict | None) -> dict[str, list[str]]:
    """
    从错误 JSON 数据中提取按类别分类的错误单词列表。

    支持多种字段名（transcribed, standard, word, text, error_word, expected），
    自动处理嵌套字典情况。

    参数:
        errors_data: read_errors_json() 返回的字典，或 None

    返回:
        {"replace": [...], "insert": [...], "delete": [...]}
    """
    result: dict[str, list[str]] = {
        ERROR_TYPE_REPLACE: [],
        ERROR_TYPE_INSERT: [],
        ERROR_TYPE_DELETE: [],
    }

    if not errors_data:
        return result

    errors = errors_data.get("errors", {})

    for category in ERROR_CATEGORIES:
        err_list = errors.get(category, [])
        for err in err_list:
            word = None
            if isinstance(err, dict):
                # 按优先级尝试多种可能的字段名
                word = (
                    err.get("transcribed")
                    or err.get("standard")
                    or err.get("word")
                    or err.get("text")
                    or err.get("error_word")
                    or err.get("expected")
                )
                # 如果 word 本身是嵌套字典，尝试提取值
                if isinstance(word, dict):
                    word = word.get("word", word.get("text", str(word)))
            elif isinstance(err, str):
                word = err
            else:
                continue

            if word and isinstance(word, str):
                word = word.strip().lower()
                if word and len(word) > 1:
                    result[category].append(word)

    return result


# ==============================================================================
# 词云渲染 — 频次彩色渲染 + 单色回退
# ==============================================================================

def get_color_func(word_freq: Counter):
    """
    根据词频生成颜色映射函数。

    高频词使用暖色（红/橙），低频词使用冷色（蓝/紫），
    视觉上直观区分错误严重程度。

    参数:
        word_freq: 词→频次 Counter

    返回:
        color_func 回调（供 WordCloud 使用）
    """
    if not word_freq:
        return lambda *args, **kwargs: "#455a64"

    max_freq = max(word_freq.values())
    min_freq = min(word_freq.values())
    range_freq = max_freq - min_freq if max_freq > min_freq else 1

    # 颜色梯度：暖色(高频) → 冷色(低频)
    colors = [
        "#e74c3c",  # 红色 (最高频)
        "#e67e22",  # 橙色
        "#f1c40f",  # 黄色
        "#2ecc71",  # 绿色
        "#3498db",  # 蓝色
        "#9b59b6",  # 紫色
        "#1abc9c",  # 青色
        "#e84393",  # 粉色
    ]

    def color_func(word, _font_size, _position, _orientation,
                   _random_state=None, **_kwargs):
        freq = word_freq.get(word, 1)
        normalized = (freq - min_freq) / range_freq
        idx = int(normalized * (len(colors) - 1))
        idx = min(idx, len(colors) - 1)
        return colors[idx]

    return color_func


def _find_chinese_font_path() -> str | None:
    """在系统中查找可用的中文字体文件路径。"""
    candidates = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/simkai.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    try:
        for _f in fm.fontManager.ttflist:
            if any(kw in _f.name.lower() for kw in
                   ("simhei", "yahei", "simsun", "simkai", "cjk", "wqy",
                    "pingfang", "noto sans", "wenquan")):
                return _f.fname
    except Exception:
        pass
    return None


def _render_wordcloud(
    word_freq: Counter,
    title: str,
    color: str,
    output_path: str,
) -> None:
    """
    使用 wordcloud 库渲染单张词云图（单色模式，保留作为回退）。

    所有样式参数从 _config.wordcloud 读取，停用词已在调用前过滤。

    参数:
        word_freq:   词 → 频次映射
        title:       图表标题
        color:       主色调（十六进制）
        output_path: 输出 PNG 路径
    """
    try:
        from wordcloud import WordCloud
    except ImportError:
        print("[词云] wordcloud 库未安装，回退到 matplotlib 替代方案")
        _render_fallback_wordcloud(word_freq, title, color, output_path)
        return

    wc_config = _config.wordcloud
    font_path = _find_chinese_font_path()
    if font_path:
        print(f"[词云] 使用字体: {font_path}")

    wc = WordCloud(
        width=wc_config.width,
        height=wc_config.height,
        background_color=wc_config.background_color,
        color_func=lambda *args, **kwargs: color,
        max_words=wc_config.max_words,
        max_font_size=wc_config.max_font_size,
        min_font_size=wc_config.min_font_size,
        collocations=False,
        font_path=font_path,
        prefer_horizontal=wc_config.prefer_horizontal,
    )
    wc.generate_from_frequencies(word_freq)

    fig, ax = plt.subplots(figsize=(10, 7.5))
    ax.imshow(wc, interpolation="bilinear")
    ax.set_title(title, fontsize=16, fontweight="bold", pad=15)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_wordcloud_colorful(
    word_freq: Counter,
    title: str,
    output_path: str,
    background_color: str = "white",
    max_words: int | None = None,
) -> None:
    """
    使用频次彩色渲染生成词云图（当前默认渲染方式）。

    高频词用暖色调、低频词用冷色调，并附加统计文本框。
    样式参数优先使用 _config.wordcloud 的值。

    参数:
        word_freq:        词 → 频次映射
        title:            图表标题
        output_path:      输出 PNG 路径
        background_color: 背景色
        max_words:        最大单词数（None=使用配置值）
    """
    try:
        from wordcloud import WordCloud
    except ImportError:
        print("[词云] wordcloud 库未安装，回退到 matplotlib 替代方案")
        _render_fallback_wordcloud(word_freq, title, "#455a64", output_path)
        return

    if not word_freq:
        print("[词云] 无数据，跳过")
        return

    wc_config = _config.wordcloud
    if max_words is None:
        max_words = wc_config.max_words

    font_path = _find_chinese_font_path()

    # 获取频次颜色函数
    color_func = get_color_func(word_freq)

    wc = WordCloud(
        width=wc_config.width,
        height=wc_config.height,
        background_color=background_color,
        color_func=color_func,
        max_words=max_words,
        max_font_size=wc_config.max_font_size or 150,
        min_font_size=wc_config.min_font_size,
        collocations=False,
        font_path=font_path,
        prefer_horizontal=wc_config.prefer_horizontal,
        random_state=42,
        scale=1.5,
        contour_width=1,
        contour_color="#bdc3c7",
    )
    wc.generate_from_frequencies(word_freq)

    fig, ax = plt.subplots(figsize=(14, 10))
    ax.imshow(wc, interpolation="bilinear")
    ax.set_title(title, fontsize=20, fontweight="bold", pad=20, color="#2c3e50")
    ax.axis("off")

    # 统计信息文本框
    ax.text(
        0.98, 0.02,
        f"共 {len(word_freq)} 个不同单词\n最高频: {max(word_freq.values())} 次",
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment="bottom",
        horizontalalignment="right",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )

    plt.tight_layout(pad=0)
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[词云] 已生成: {output_path}")


def _render_fallback_wordcloud(
    word_freq: Counter,
    title: str,
    color: str,
    output_path: str,
) -> None:
    """wordcloud 库不可用时的回退方案：横向柱状图展示 Top 20 高频词。"""
    top_words = word_freq.most_common(20)
    if not top_words:
        return

    words, counts = zip(*top_words)

    fig, ax = plt.subplots(figsize=(12, 8))
    y_pos = range(len(words))
    ax.barh(y_pos, counts, color=color, alpha=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(words)
    ax.invert_yaxis()
    ax.set_xlabel("出现次数", fontsize=12)
    ax.set_title(f"{title} — Top 20 高频词", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ==============================================================================
# CSV 导出 — 错误单词 + 频次
# ==============================================================================

def export_errors_to_csv(
    error_words: dict[str, list[str]],
    output_path: str,
) -> str:
    """
    将按类别分类的错误单词导出为单个汇总 CSV 文件。

    CSV 包含三列：错误单词、频次、错误类型，按错误类型分组、
    频次降序排列。

    参数:
        error_words: {"replace": [...], "insert": [...], "delete": [...]}
        output_path: CSV 输出路径

    返回:
        写入的 CSV 路径，无数据时返回空字符串
    """
    if not error_words:
        print("[导出] 无错误数据，跳过")
        return ""

    records = []
    for error_type, words in error_words.items():
        word_freq = Counter(words)
        for word, count in word_freq.most_common():
            records.append({
                "错误单词": word,
                "频次": count,
                "错误类型": error_type,
            })

    if not records:
        return ""

    df = pd.DataFrame(records)
    df = df.sort_values(["错误类型", "频次"], ascending=[True, False])

    ensure_dir(os.path.dirname(output_path))
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[导出] 错误汇总 CSV: {output_path} ({len(df)} 条)")
    return output_path


# ==============================================================================
# 词云生成（主函数）
# ==============================================================================

def generate_error_wordclouds(
    result_dir: str,
    output_dir: str = "",
    export_csv: bool = True,
) -> dict[str, str]:
    """
    解析 result_dir 下所有学生的 _errors.json，生成 4 张词云图 + CSV 汇总。

    处理流程：
      1. 收集所有 _errors.json → 提取错误单词
      2. spaCy 词性还原（可通过 config 开关控制）
      3. 停用词过滤
      4. 按频次彩色渲染生成 4 张词云图
      5. 导出错误汇总 CSV

    生成文件：
      - wordcloud_replace.png  : 替换错误词云
      - wordcloud_insert.png   : 多读错误词云
      - wordcloud_delete.png   : 漏读错误词云
      - wordcloud_all.png      : 三合一汇总词云
      - error_summary.csv      : 所有错误单词 + 频次 + 类型

    参数:
        result_dir: resource/result/ 目录路径
        output_dir: 输出目录（默认: result_dir/error_analysis/）
        export_csv: 是否导出 CSV（默认 True）

    返回:
        {"replace": path, "insert": path, "delete": path, "all": path}
    """
    if not output_dir:
        output_dir = os.path.join(result_dir, "error_analysis")
    ensure_dir(output_dir)

    # ---- 1. 加载停用词 ----
    project_root = Path(result_dir).parent.parent
    stopwords_set = load_stopwords_from_file(_config, project_root)

    # ---- 2. 收集所有学生的错误数据 ----
    error_words: dict[str, list[str]] = {
        ERROR_TYPE_REPLACE: [],
        ERROR_TYPE_INSERT: [],
        ERROR_TYPE_DELETE: [],
    }
    all_words: list[str] = []

    student_count = 0
    total_errors = 0
    filtered_errors = 0

    for item in os.listdir(result_dir):
        student_dir = os.path.join(result_dir, item)
        if not os.path.isdir(student_dir):
            continue
        if item in ("history", "error_analysis", "progress_curves"):
            continue

        for f in os.listdir(student_dir):
            if f.endswith("_errors.json"):
                json_path = os.path.join(student_dir, f)
                errors_data = read_errors_json(json_path)
                if errors_data is None:
                    continue

                # 使用增强的错误词提取函数
                student_errors = extract_error_words_from_json(errors_data)

                for category in ERROR_CATEGORIES:
                    for word in student_errors.get(category, []):
                        total_errors += 1
                        # spaCy 词性还原
                        lemma = lemmatize_word(word)
                        if lemma and len(lemma) > 1 and lemma not in stopwords_set:
                            error_words[category].append(lemma)
                            all_words.append(lemma)
                            filtered_errors += 1

                student_count += 1
                break

    print(f"[词云] 共读取 {student_count} 名学生的错误数据")
    print(f"[词云] 错误词: {total_errors} → {filtered_errors} (过滤后)")

    if stopwords_set and isinstance(_config.wordcloud.stopwords, list):
        print(f"[词云] 停用词 ({len(stopwords_set)} 个)")

    # ---- 3. 导出 CSV ----
    if export_csv:
        csv_path = os.path.join(output_dir, "error_summary.csv")
        export_errors_to_csv(error_words, csv_path)

    # ---- 4. 生成 3 张分类词云 + 1 张三合一 ----
    category_labels = {
        ERROR_TYPE_REPLACE: "替换错误 (Replace)",
        ERROR_TYPE_INSERT: "多读错误 (Insert)",
        ERROR_TYPE_DELETE: "漏读错误 (Delete)",
    }

    output_paths: dict[str, str] = {}

    for category in ERROR_CATEGORIES:
        words = error_words[category]
        if not words:
            print(f"[词云] {category_labels[category]}: 无数据，跳过")
            continue

        word_freq = Counter(words)
        # 防御性过滤（再次确保停用词不在 Counter 中）
        word_freq = Counter(
            {w: c for w, c in word_freq.items()
             if w not in stopwords_set and len(w) > 1}
        )

        if not word_freq:
            continue

        output_path = os.path.join(output_dir, f"wordcloud_{category}.png")
        _render_wordcloud_colorful(
            word_freq=word_freq,
            title=category_labels[category],
            output_path=output_path,
        )
        output_paths[category] = output_path
        print(f"[词云] {category_labels[category]}: "
              f"{len(word_freq)} 个词 → {output_path}")

    # ---- 5. 生成三合一汇总词云 ----
    if all_words:
        all_freq = Counter(all_words)
        all_freq = Counter(
            {w: c for w, c in all_freq.items()
             if w not in stopwords_set and len(w) > 1}
        )
        if all_freq:
            all_path = os.path.join(output_dir, "wordcloud_all.png")
            _render_wordcloud_colorful(
                word_freq=all_freq,
                title="全部错误汇总 (All Errors)",
                output_path=all_path,
                max_words=300,
            )
            output_paths["all"] = all_path
            print(f"[词云] 全部错误汇总: {len(all_freq)} 个词 → {all_path}")

    return output_paths


# ==============================================================================
# 历史进步曲线 — 每位学生一张独立图
# ==============================================================================

def generate_progress_curves(
    history_dir: str,
    output_dir: str = "",
) -> list[str]:
    """
    读取 history_dir 下所有归档的 summary.csv，为每位学生生成一张
    独立的折线图（3 条线：准确率/语音综合分/总成绩），
    统一输出到 progress_curves/ 子目录，覆盖上一次生成的结果。

    参数:
        history_dir: resource/result/history/ 目录路径
        output_dir:  输出目录（为空则默认 history_dir/../error_analysis/progress_curves/）

    返回:
        生成的 PNG 文件路径列表
    """
    if not output_dir:
        output_dir = os.path.join(
            os.path.dirname(history_dir), "error_analysis", "progress_curves"
        )
    # 确保输出到独立子目录，避免覆盖词云等兄弟文件
    if os.path.basename(output_dir) != "progress_curves":
        output_dir = os.path.join(output_dir, "progress_curves")
    # 清除旧输出后重建（确保覆盖）
    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    ensure_dir(output_dir)

    # ---- 1. 收集所有归档文件 ----
    archive_files = sorted(
        [f for f in os.listdir(history_dir) if f.endswith("_summary.csv")],
    )
    if not archive_files:
        print("[历史曲线] 无归档文件，跳过")
        return []

    print(f"[历史曲线] 找到 {len(archive_files)} 次历史运行记录")

    # ---- 2. 合并所有历史数据 ----
    all_records: list[dict] = []
    for filename in archive_files:
        timestamp_str = filename.replace("_summary.csv", "")
        try:
            run_time = datetime.strptime(timestamp_str, "%Y-%m-%d_%H%M%S")
        except ValueError:
            run_time = datetime.now()

        file_path = os.path.join(history_dir, filename)
        try:
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        except Exception:
            continue

        for _, row in df.iterrows():
            all_records.append({
                "学生": str(row.get("学生", "")),
                "时间": run_time,
                "单词准确率": _parse_percent(row.get("单词准确率", "0%")),
                "语音综合分": _parse_float(row.get("语音综合分", 0)),
                "总成绩": _parse_float(row.get("总成绩", 0)),
            })

    if not all_records:
        print("[历史曲线] 无有效数据，跳过")
        return []

    df_all = pd.DataFrame(all_records)
    students = sorted(df_all["学生"].unique())
    output_paths: list[str] = []

    # ---- 3. 为每位学生生成独立折线图 ----
    for student in students:
        student_data = df_all[df_all["学生"] == student].sort_values("时间")
        n_runs = len(student_data)

        # 文件名去空格和特殊字符
        safe_name = student.replace(" ", "_").replace("/", "_")
        out_path = os.path.join(output_dir, f"{safe_name}_progress.png")

        fig, ax = plt.subplots(figsize=(8, 5))

        if n_runs == 1:
            # 仅一次记录：标注无法绘制趋势
            for _, point in student_data.iterrows():
                ax.scatter(point["时间"], point["单词准确率"] * 100,
                          color="#1976d2", s=80, zorder=5)
                ax.scatter(point["时间"], point["语音综合分"],
                          color="#388e3c", s=80, zorder=5)
                ax.scatter(point["时间"], point["总成绩"],
                          color="#d32f2f", s=80, zorder=5)
            title = f"{student}（仅 1 次记录，无趋势）"
        else:
            times = student_data["时间"].tolist()
            ax.plot(times, student_data["单词准确率"] * 100, "o-",
                    color="#1976d2", linewidth=2, markersize=6,
                    label="单词准确率 (%)")
            ax.plot(times, student_data["语音综合分"], "s-",
                    color="#388e3c", linewidth=2, markersize=6,
                    label="语音综合分")
            ax.plot(times, student_data["总成绩"], "^-",
                    color="#d32f2f", linewidth=2, markersize=6,
                    label="总成绩")
            title = f"{student}（{n_runs} 次运行）"

        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_ylabel("分数", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 105)
        if n_runs > 1:
            ax.legend(loc="lower left", fontsize=9)

        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_fontsize(8)

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        output_paths.append(out_path)

    print(f"[历史曲线] {len(students)} 名学生各一张图 → {output_dir}/")
    return output_paths


# ==============================================================================
# 结果归档
# ==============================================================================

def archive_current_result(summary_csv: str, history_dir: str) -> str:
    """
    将当前 summary.csv 归档到 history_dir，同时写入 meta.json。

    meta.json 记录本次运行的基本信息，供历史曲线模块分类和过滤使用。

    参数:
        summary_csv: 当前 resource/result/summary.csv 路径
        history_dir: 归档目录

    返回:
        归档后的 CSV 文件路径
    """
    ensure_dir(history_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # 复制 summary.csv
    archive_name = f"{timestamp}_summary.csv"
    archive_path = os.path.join(history_dir, archive_name)
    shutil.copy2(summary_csv, archive_path)
    print(f"[归档] summary.csv → {archive_path}")

    # 写入 meta.json
    try:
        df = pd.read_csv(summary_csv, encoding="utf-8-sig")
        students = df["学生"].tolist() if "学生" in df.columns else []
        meta = {
            "timestamp": timestamp,
            "student_count": len(students),
            "students": students,
        }
        meta_path = os.path.join(history_dir, f"{timestamp}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[归档] meta.json → {meta_path}")
    except Exception as e:
        print(f"[归档] meta.json 写入失败: {e}")

    return archive_path


# ==============================================================================
# 内部辅助
# ==============================================================================

def _parse_percent(val) -> float:
    """解析百分比字符串（如 "85.23%" → 0.8523）。"""
    if isinstance(val, (int, float)):
        return float(val) if float(val) <= 1.0 else float(val) / 100.0
    try:
        return float(str(val).replace("%", "")) / 100.0
    except (ValueError, TypeError):
        return 0.0


def _parse_float(val) -> float:
    """安全解析浮点数。"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ==============================================================================
# 独立运行入口
# ==============================================================================
def _main() -> None:
    """命令行独立调用入口。"""
    parser = argparse.ArgumentParser(
        description="错题可视化：生成词云图和历史进步曲线"
    )
    parser.add_argument(
        "--result-dir", required=True,
        help="resource/result/ 目录路径"
    )
    parser.add_argument(
        "--output-dir", default="",
        help="输出目录（默认: result_dir/error_analysis/）"
    )
    parser.add_argument(
        "--history-dir", default="",
        help="历史归档目录（默认: result_dir/history/）"
    )
    parser.add_argument(
        "--no-csv", action="store_true",
        help="不导出 CSV 频次文件"
    )
    args = parser.parse_args()

    result_dir = args.result_dir
    output_dir = args.output_dir or os.path.join(result_dir, "error_analysis")
    history_dir = args.history_dir or os.path.join(result_dir, "history")

    # 词云
    print("=" * 60)
    print("生成错题词云...")
    generate_error_wordclouds(result_dir, output_dir, export_csv=not args.no_csv)

    # 历史曲线
    print("\n" + "=" * 60)
    print("生成历史进步曲线...")
    generate_progress_curves(history_dir, output_dir)


if __name__ == "__main__":
    _main()
