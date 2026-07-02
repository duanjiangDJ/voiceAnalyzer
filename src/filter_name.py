"""
filter_name.py — 数据完整性预检查
==================================
提取音频文件夹中的文件名（不含扩展名），与 summary.csv 中的学生列表
进行交叉对比，找出尚未处理或遗漏的学生。

公共 API:
    filter_precheck() — 主入口，从 launcher 或独立命令行调用

依赖:
    - pandas (第三方)
    - src.utils: extract_student_id
"""

import argparse
import os
import sys

# 添加项目根目录到 path（支持独立运行）
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.utils import extract_student_id


def filter_precheck(
    audio_dir: str,
    summary_csv_path: str,
    name_csv: str = "",
    missing_csv: str = "",
) -> list[str]:
    """
    预检查：提取音频文件夹中的文件名（不含扩展名），与 summary.csv
    中学生列表对比，找出音频文件夹中存在但 summary 中缺失的记录。

    用途:
        在运行分析前校验数据完整性，确保每个音频文件都有对应记录。

    参数:
        audio_dir:        仿读音频文件夹路径
        summary_csv_path: summary.csv 路径（含已处理学生列表）
        name_csv:         输出的文件名列表 CSV 路径（空字符串则不生成）
        missing_csv:      输出的缺失记录 CSV 路径（空字符串则不生成）

    返回:
        missing_in_summary: 音频文件夹中有但 summary 中未找到的学生名列表

    异常:
        FileNotFoundError: 目录或文件不存在
    """
    # ---- 1. 验证路径 ----
    if not os.path.isdir(audio_dir):
        raise FileNotFoundError(f"音频文件夹不存在: {audio_dir}")
    if not os.path.exists(summary_csv_path):
        raise FileNotFoundError(f"summary.csv 不存在: {summary_csv_path}")

    # ---- 2. 提取音频文件名（不含扩展名） ----
    filenames_without_ext = []
    for file in os.listdir(audio_dir):
        full_path = os.path.join(audio_dir, file)
        if os.path.isfile(full_path):
            name = os.path.splitext(file)[0]
            filenames_without_ext.append(name)

    print(f"[预检查] 音频文件夹: {audio_dir}")
    print(f"[预检查] 找到 {len(filenames_without_ext)} 个音频文件")

    # ---- 3. 可选: 保存文件名列表 ----
    if name_csv:
        df_names = pd.DataFrame({
            "序号": range(1, len(filenames_without_ext) + 1),
            "name": filenames_without_ext,
        })
        df_names.to_csv(name_csv, index=False, encoding="utf-8-sig")
        print(f"[预检查] 文件名列表已保存: {name_csv}")

    # ---- 4. 读取 summary.csv ----
    summary_df = pd.read_csv(summary_csv_path, encoding="utf-8-sig")
    if "学生" not in summary_df.columns:
        raise ValueError(
            f"summary.csv 中缺少 '学生' 列。可用列: {summary_df.columns.tolist()}"
        )

    summary_students = summary_df["学生"].str.strip().tolist()
    summary_set = set(summary_students)

    # ---- 5. 交叉对比 ----
    missing_in_summary = [
        name for name in filenames_without_ext
        if name not in summary_set
    ]

    print(f"[预检查] summary.csv 中有 {len(summary_students)} 条记录")
    print(f"[预检查] 音频中有但 summary 中缺失: {len(missing_in_summary)} 条")

    if missing_in_summary:
        print("-" * 60)
        print("以下文件在音频文件夹中存在，但 summary.csv 中找不到:")
        for i, name in enumerate(missing_in_summary, 1):
            print(f"  {i:3d}. {name}")
        print("-" * 60)

        if missing_csv:
            df_missing = pd.DataFrame({
                "序号": range(1, len(missing_in_summary) + 1),
                "name": missing_in_summary,
            })
            df_missing.to_csv(missing_csv, index=False, encoding="utf-8-sig")
            print(f"[预检查] 缺失记录已保存: {missing_csv}")
    else:
        print("[预检查] ✓ 所有音频文件都在 summary.csv 中有对应记录")

    return missing_in_summary


# ==============================================================================
# 独立运行入口
# ==============================================================================
def _main() -> None:
    """命令行独立调用入口。"""
    parser = argparse.ArgumentParser(
        description="对比音频文件夹与 summary.csv，找出缺失的学生记录"
    )
    parser.add_argument(
        "--audio-dir", required=True,
        help="仿读音频文件夹路径"
    )
    parser.add_argument(
        "--summary", required=True,
        help="summary.csv 文件路径"
    )
    parser.add_argument(
        "--name-csv", default="",
        help="输出的文件名列表 CSV 路径（可选）"
    )
    parser.add_argument(
        "--missing-csv", default="missing_records.csv",
        help="输出的缺失记录 CSV 路径（默认: missing_records.csv）"
    )
    args = parser.parse_args()

    filter_precheck(
        audio_dir=args.audio_dir,
        summary_csv_path=args.summary,
        name_csv=args.name_csv,
        missing_csv=args.missing_csv,
    )


if __name__ == "__main__":
    _main()
