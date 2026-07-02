"""
error_visualizer.py — 错题可视化：词云 + 历史进步曲线
======================================================
对学生文本比对中的错误进行聚合分析和可视化展示。

功能:
    1. 错题词云：按替换/多读/漏读三分类，统计错误词频，生成词云图
    2. 历史进步曲线：按学生绘制多维度评分随时间变化的折线图

公共 API:
    generate_error_wordclouds()  — 生成三分类词云图
    generate_progress_curves()   — 生成历史进步曲线
    archive_current_result()     — 归档本次运行结果

数据来源:
    - 词云: 每位学生的 _errors.json（由 text_llm.py 生成）
    - 曲线: resource/result/history/ 下归档的 summary.csv

依赖:
    - matplotlib, pandas (第三方)
    - wordcloud (第三方，需单独安装)
    - src.utils: ensure_dir
    - src.constants: ERROR_TYPE_REPLACE, ERROR_TYPE_INSERT, ERROR_TYPE_DELETE, WORDCLOUD_COLORS
"""

import argparse
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
import numpy as np
import pandas as pd

from src.constants import (
    ERROR_CATEGORIES,
    ERROR_TYPE_DELETE,
    ERROR_TYPE_INSERT,
    ERROR_TYPE_REPLACE,
    WORDCLOUD_COLORS,
)
from src.utils import ensure_dir, read_errors_json


# ==============================================================================
# 词云生成
# ==============================================================================

def generate_error_wordclouds(
    result_dir: str,
    output_dir: str = "",
) -> dict[str, str]:
    """
    解析 result_dir 下所有学生的 _errors.json，按错误类型（替换/多读/漏读）
    分别生成词云图，保存到 output_dir。

    参数:
        result_dir: resource/result/ 目录路径（含学生子文件夹）
        output_dir: 词云图输出目录（为空则默认 result_dir/error_analysis/）

    返回:
        {"replace": path, "insert": path, "delete": path} — 三张词云图路径
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

    student_count = 0
    for item in os.listdir(result_dir):
        student_dir = os.path.join(result_dir, item)
        if not os.path.isdir(student_dir):
            continue
        # 跳过特殊目录
        if item in ("history", "error_analysis"):
            continue

        # 查找 _errors.json
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
                            # replace 类型: {"standard": "word", "transcribed": "word"}
                            word = err.get("transcribed", err.get("standard", ""))
                        elif isinstance(err, str):
                            word = err
                        else:
                            continue
                        word = word.strip().lower()
                        if word and len(word) > 1:  # 过滤单字母噪声
                            error_words[category].append(word)
                student_count += 1
                break  # 每个学生只处理一个 errors.json

    print(f"[词云] 共读取 {student_count} 名学生的错误数据")

    # ---- 2. 对每类错误生成词云 ----
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

        # 统计词频
        word_freq = Counter(words)

        output_path = os.path.join(output_dir, f"wordcloud_{category}.png")
        _render_wordcloud(
            word_freq=word_freq,
            title=category_labels[category],
            color=WORDCLOUD_COLORS.get(category, "#333333"),
            output_path=output_path,
        )
        output_paths[category] = output_path
        print(f"[词云] {category_labels[category]}: {len(word_freq)} 个不同词 → {output_path}")

    # ---- 3. 生成三合一拼接图 ----
    if len(output_paths) >= 2:
        combined_path = os.path.join(output_dir, "wordcloud_combined.png")
        _render_combined_wordclouds(output_paths, combined_path)
        output_paths["combined"] = combined_path

    return output_paths


def _render_wordcloud(
    word_freq: Counter,
    title: str,
    color: str,
    output_path: str,
) -> None:
    """
    使用 wordcloud 库渲染单张词云图。

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

    # 创建词云
    wc = WordCloud(
        width=800,
        height=600,
        background_color="white",
        color_func=lambda *args, **kwargs: color,
        max_words=100,
        collocations=False,
        font_path=None,  # 使用默认字体
        prefer_horizontal=0.7,
    )
    wc.generate_from_frequencies(word_freq)

    # 渲染
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
    """
    wordcloud 库不可用时的回退方案：横向柱状图展示 Top 20 高频词。
    """
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


def _render_combined_wordclouds(
    output_paths: dict[str, str],
    combined_path: str,
) -> None:
    """将多张词云图水平拼接为一张大图。"""
    valid_paths = [p for p in output_paths.values() if os.path.exists(p)]
    if len(valid_paths) < 2:
        return

    fig, axes = plt.subplots(1, len(valid_paths), figsize=(6 * len(valid_paths), 5))
    if len(valid_paths) == 1:
        axes = [axes]

    for ax, path in zip(axes, valid_paths):
        img = plt.imread(path)
        ax.imshow(img)
        ax.axis("off")

    fig.tight_layout()
    fig.savefig(combined_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ==============================================================================
# 历史进步曲线
# ==============================================================================

def generate_progress_curves(
    history_dir: str,
    output_path: str = "",
) -> str:
    """
    读取 history_dir 下所有归档的 summary.csv，为每位学生绘制
    准确率 + 语音综合分随时间变化的折线图。

    参数:
        history_dir: resource/result/history/ 目录路径
        output_path: 输出图片路径（为空则默认 history_dir/../error_analysis/progress_curves.png）

    返回:
        输出图片的绝对路径
    """
    if not output_path:
        output_path = os.path.join(
            os.path.dirname(history_dir), "error_analysis", "progress_curves.png"
        )
    ensure_dir(os.path.dirname(output_path))

    # ---- 1. 收集所有归档文件 ----
    archive_files = sorted(
        [f for f in os.listdir(history_dir) if f.endswith("_summary.csv")],
    )
    if len(archive_files) < 2:
        print(f"[历史曲线] 归档文件不足（需要至少 2 次运行，当前 {len(archive_files)} 次），跳过")
        # 即使只有一次也生成（显示当前分数）
        if len(archive_files) == 0:
            return ""

    print(f"[历史曲线] 找到 {len(archive_files)} 次历史运行记录")

    # ---- 2. 合并所有历史数据 ----
    all_records: list[dict] = []
    for filename in archive_files:
        # 从文件名提取时间戳: {YYYY-MM-DD_HHMMSS}_summary.csv
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
            record = {
                "学生": str(row.get("学生", "")),
                "时间": run_time,
                "单词准确率": _parse_percent(row.get("单词准确率", "0%")),
                "语音综合分": _parse_float(row.get("语音综合分", 0)),
                "总成绩": _parse_float(row.get("总成绩", 0)),
            }
            all_records.append(record)

    if not all_records:
        print("[历史曲线] 无有效数据，跳过")
        return ""

    df_all = pd.DataFrame(all_records)
    students = sorted(df_all["学生"].unique())

    # ---- 3. 绘制每位学生的子图 ----
    n_students = len(students)
    n_cols = min(3, n_students)
    n_rows = (n_students + n_cols - 1) // n_cols

    fig, axes = plt.subplots(
        n_rows, n_cols,
        figsize=(6 * n_cols, 4 * n_rows),
        squeeze=False,
    )

    for i, student in enumerate(students):
        row, col = i // n_cols, i % n_cols
        ax = axes[row][col]

        student_data = df_all[df_all["学生"] == student].sort_values("时间")

        if len(student_data) < 2:
            # 只有一次数据：显示为散点
            for _, point in student_data.iterrows():
                ax.scatter(point["时间"], point["单词准确率"] * 100, color="#1976d2", s=60, zorder=5)
                ax.scatter(point["时间"], point["语音综合分"], color="#388e3c", s=60, zorder=5)
                ax.scatter(point["时间"], point["总成绩"], color="#d32f2f", s=60, zorder=5)
        else:
            times = student_data["时间"].tolist()
            ax.plot(times, student_data["单词准确率"] * 100, "o-", color="#1976d2",
                    linewidth=2, markersize=6, label="单词准确率 (%)")
            ax.plot(times, student_data["语音综合分"], "s-", color="#388e3c",
                    linewidth=2, markersize=6, label="语音综合分")
            ax.plot(times, student_data["总成绩"], "^-", color="#d32f2f",
                    linewidth=2, markersize=6, label="总成绩")

        ax.set_title(student, fontsize=11, fontweight="bold")
        ax.set_ylabel("分数", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 105)

        # 旋转 X 轴标签防止重叠
        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_fontsize(8)

    # 隐藏多余的子图
    for i in range(n_students, n_rows * n_cols):
        row, col = i // n_cols, i % n_cols
        axes[row][col].set_visible(False)

    # 统一图例
    if n_students > 0:
        handles, labels = axes[0][0].get_legend_handles_labels()
        if handles:
            fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=10)

    fig.suptitle("学生仿读成绩历史趋势", fontsize=16, fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"[历史曲线] {n_students} 名学生趋势图已保存: {output_path}")
    return output_path


# ==============================================================================
# 结果归档
# ==============================================================================

def archive_current_result(summary_csv: str, history_dir: str) -> str:
    """
    将当前 summary.csv 归档到 history_dir，文件名带时间戳。

    参数:
        summary_csv: 当前 resource/result/summary.csv 路径
        history_dir: 归档目录

    返回:
        归档后的文件路径
    """
    ensure_dir(history_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive_name = f"{timestamp}_summary.csv"
    archive_path = os.path.join(history_dir, archive_name)
    shutil.copy2(summary_csv, archive_path)
    print(f"[归档] summary.csv → {archive_path}")
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
    generate_progress_curves(history_dir, os.path.join(output_dir, "progress_curves.png"))


if __name__ == "__main__":
    _main()
