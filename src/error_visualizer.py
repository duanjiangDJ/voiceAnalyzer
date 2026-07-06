"""
error_visualizer.py — 错题可视化：词云 + 历史进步曲线
======================================================
对学生文本比对中的错误进行聚合分析和可视化展示。

功能:
    1. 错题词云：4 张图（替换/多读/漏读 + 三合一合计），
       停用词过滤、全横向排列、参数可配置
    2. 历史进步曲线：每位学生一张独立折线图，展示历次运行趋势
    3. 结果归档：每次运行写入 history/ 并附带 meta.json

公共 API:
    generate_error_wordclouds()  — 生成 4 张词云图
    generate_progress_curves()   — 生成每位学生的历史曲线
    archive_current_result()     — 归档本次运行结果（含 meta.json）

数据来源:
    - 词云: 每位学生的 _errors.json（由 text_llm.py 生成）
    - 曲线: resource/result/history/ 下归档的 summary.csv

依赖:
    - matplotlib, pandas, numpy (第三方)
    - wordcloud (第三方，需单独安装)
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
    WORDCLOUD_COLORS,
)
from src.utils import ensure_dir, read_errors_json

# 模块级配置
_config = AppConfig.load()


# ==============================================================================
# 词云生成
# ==============================================================================

def generate_error_wordclouds(
    result_dir: str,
    output_dir: str = "",
) -> dict[str, str]:
    """
    解析 result_dir 下所有学生的 _errors.json，按错误类型生成 4 张词云图：
      - wordcloud_replace.png : 替换错误
      - wordcloud_insert.png  : 多读错误
      - wordcloud_delete.png  : 漏读错误
      - wordcloud_all.png     : 三种错误合计

    停用词（the/of/to 等）从 _config.wordcloud.stopwords 读取并过滤。
    所有词强制横向排列（prefer_horizontal=1.0）。

    参数:
        result_dir: resource/result/ 目录路径
        output_dir: 输出目录（默认: result_dir/error_analysis/）

    返回:
        {"replace": path, "insert": path, "delete": path, "all": path}
    """
    if not output_dir:
        output_dir = os.path.join(result_dir, "error_analysis")
    ensure_dir(output_dir)

    # ---- 1. 收集所有学生的错误数据 ----
    error_words: dict[str, list[str]] = {
        ERROR_TYPE_REPLACE: [],
        ERROR_TYPE_INSERT: [],
        ERROR_TYPE_DELETE: [],
    }
    all_words: list[str] = []

    stopwords_set = set(w.lower() for w in _config.wordcloud.stopwords)
    student_count = 0

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
                errors = errors_data.get("errors", {})
                for category in ERROR_CATEGORIES:
                    err_list = errors.get(category, [])
                    for err in err_list:
                        if isinstance(err, dict):
                            word = err.get(
                                "transcribed",
                                err.get("standard",
                                        err.get("word", ""))
                            )
                        elif isinstance(err, str):
                            word = err
                        else:
                            continue
                        word = word.strip().lower()
                        if word and len(word) > 1 and word not in stopwords_set:
                            error_words[category].append(word)
                            all_words.append(word)
                student_count += 1
                break

    print(f"[词云] 共读取 {student_count} 名学生的错误数据")

    # ---- 2. 打印停用词过滤统计 ----
    stopwords_filtered = 0
    for category in ERROR_CATEGORIES:
        raw = error_words[category]
        # 停用词已在上面的循环中过滤，此处仅打印
    if stopwords_set:
        print(f"[词云] 停用词列表 ({len(stopwords_set)} 个): "
              f"{', '.join(sorted(list(stopwords_set)[:10]))}...")

    # ---- 3. 生成 3 张分类词云 + 1 张三合一 ----
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
        before_count = len(word_freq)
        # 再次过滤（防御性：确保停用词不在 Counter 中）
        word_freq = Counter(
            {w: c for w, c in word_freq.items()
             if w not in stopwords_set and len(w) > 1}
        )
        after_count = len(word_freq)
        if before_count > after_count:
            print(f"[词云] {category_labels[category]}: "
                  f"过滤掉 {before_count - after_count} 个停用词/短词")

        output_path = os.path.join(output_dir, f"wordcloud_{category}.png")
        _render_wordcloud(
            word_freq=word_freq,
            title=category_labels[category],
            color=WORDCLOUD_COLORS.get(category, "#333333"),
            output_path=output_path,
        )
        output_paths[category] = output_path
        print(f"[词云] {category_labels[category]}: "
              f"{len(word_freq)} 个词 → {output_path}")

    # ---- 4. 生成三合一合计词云 ----
    if all_words:
        all_freq = Counter(all_words)
        all_freq = Counter(
            {w: c for w, c in all_freq.items()
             if w not in stopwords_set and len(w) > 1}
        )
        all_path = os.path.join(output_dir, "wordcloud_all.png")
        _render_wordcloud(
            word_freq=all_freq,
            title="全部错误汇总 (All Errors)",
            color=_config.wordcloud.color_all,
            output_path=all_path,
        )
        output_paths["all"] = all_path
        print(f"[词云] 全部错误汇总: {len(all_freq)} 个词 → {all_path}")

    return output_paths


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
    使用 wordcloud 库渲染单张词云图。

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
    args = parser.parse_args()

    result_dir = args.result_dir
    output_dir = args.output_dir or os.path.join(result_dir, "error_analysis")
    history_dir = args.history_dir or os.path.join(result_dir, "history")

    # 词云
    print("=" * 60)
    print("生成错题词云...")
    generate_error_wordclouds(result_dir, output_dir)

    # 历史曲线
    print("\n" + "=" * 60)
    print("生成历史进步曲线...")
    generate_progress_curves(history_dir, output_dir)


if __name__ == "__main__":
    _main()
