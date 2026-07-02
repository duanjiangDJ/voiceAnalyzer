"""
audio_output.py — 结果后处理：将分析结果汇总到 Excel
=====================================================
读取 summary.xls/xlsx 汇总表，遍历 result/ 下各学生文件夹，
解析 .md 报告和 .png 对比图，将内容合并写入新列后保存。

公共 API:
    post_process() — 主入口，从 launcher 或独立命令行调用

依赖:
    - pandas (第三方)
    - src.utils: parse_md_report, extract_student_id, ensure_dir
    - src.constants: 共享标记
"""

import argparse
import os
import sys

# 添加项目根目录到 path（支持独立运行）
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.utils import ensure_dir, extract_student_id, parse_md_report


def post_process(
    excel_path: str,
    result_dir: str,
    output_path: str = "summary_with_details.xlsx",
    student_col: str = "学生",
    engine: str | None = None,
) -> str:
    """
    后处理：将 result 目录中每个学生的 .md 报告和 .png 图片
    合并写入 Excel 文件的新列。

    流程:
      1. 读取 Excel 汇总表
      2. 扫描 result_dir 下子文件夹，通过学号匹配学生
      3. 从 .md 提取转写文本、标准文本、比对结果
      4. 查找 .png 对比图路径
      5. 写入新 Excel 文件

    参数:
        excel_path:   输入的 summary.xls 或 .xlsx 路径
        result_dir:   result/ 目录路径（含各学生子文件夹）
        output_path:  输出的增强版 Excel 路径
        student_col:  Excel 中学生姓名列名
        engine:       pandas 读取引擎（"xlrd" for .xls, "openpyxl" for .xlsx,
                      为 None 时根据扩展名自动选择）

    返回:
        输出 Excel 文件的绝对路径

    异常:
        FileNotFoundError: excel_path 或 result_dir 不存在
        ValueError: 无法匹配学生
    """
    # ---- 1. 验证路径 ----
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")
    if not os.path.exists(result_dir):
        raise FileNotFoundError(f"结果目录不存在: {result_dir}")

    # ---- 2. 自动选择引擎 ----
    if engine is None:
        ext = os.path.splitext(excel_path)[1].lower()
        engine = "openpyxl" if ext == ".xlsx" else "xlrd"

    # ---- 3. 读取 Excel ----
    df = pd.read_excel(excel_path, engine=engine)
    print(f"[后处理] 读取 Excel: {excel_path}（{len(df)} 行）")
    print(f"[后处理] Excel 列名: {df.columns.tolist()}")

    # ---- 4. 添加新列 ----
    new_columns = ["朗读转写文本", "朗读标准文本", "比对结果", "对比图片"]
    for col in new_columns:
        if col not in df.columns:
            df[col] = ""

    # ---- 5. 建立文件夹映射（学号 → 文件夹名） ----
    folder_map: dict[str, str] = {}
    for item in os.listdir(result_dir):
        full_path = os.path.join(result_dir, item)
        if os.path.isdir(full_path):
            student_id = extract_student_id(item)
            if student_id:
                folder_map[student_id] = item
            else:
                # 无学号时直接用文件夹名
                folder_map[item] = item

    # ---- 6. 遍历每个学生 ----
    matched_count = 0
    for idx, row in df.iterrows():
        student_name = str(row[student_col]).strip()
        if not student_name:
            continue

        student_id = extract_student_id(student_name)
        if not student_id:
            print(f"  ⚠ 无法提取学号: {student_name}")
            continue

        matched_folder = folder_map.get(student_id)
        if not matched_folder:
            print(f"  ⚠ 未找到匹配文件夹: {student_name} (学号: {student_id})")
            continue

        folder_path = os.path.join(result_dir, matched_folder)

        # 查找 .md 和 .png 文件
        md_file = None
        png_file = None
        for f in os.listdir(folder_path):
            if f.endswith(".md"):
                md_file = f
            elif f.endswith(".png"):
                png_file = f

        if md_file:
            md_path = os.path.join(folder_path, md_file)
            parsed_report = parse_md_report(md_path)
            df.at[idx, "朗读转写文本"] = parsed_report["transcribe"]
            df.at[idx, "朗读标准文本"] = parsed_report["standard"]
            df.at[idx, "比对结果"] = parsed_report["compare"]
        else:
            print(f"  ⚠ {matched_folder} 缺少 .md 文件")

        if png_file:
            df.at[idx, "对比图片"] = os.path.join(matched_folder, png_file)

        matched_count += 1

    # ---- 7. 保存 ----
    ensure_dir(os.path.dirname(output_path) or ".")
    output_abs = os.path.abspath(output_path)
    df.to_excel(output_abs, index=False, engine="openpyxl")
    print(f"\n[后处理] 完成：{matched_count}/{len(df)} 名学生匹配，结果保存至: {output_abs}")

    return output_abs


# ==============================================================================
# 独立运行入口
# ==============================================================================
def _main() -> None:
    """命令行独立调用入口。"""
    parser = argparse.ArgumentParser(
        description="将 student result 中的 .md 报告合并到 Excel 汇总表"
    )
    parser.add_argument(
        "--excel", required=True,
        help="输入的 summary.xls/xlsx 路径"
    )
    parser.add_argument(
        "--result-dir", required=True,
        help="result/ 目录路径（含学生子文件夹）"
    )
    parser.add_argument(
        "--output", default="summary_with_details.xlsx",
        help="输出的增强版 Excel 路径（默认: summary_with_details.xlsx）"
    )
    parser.add_argument(
        "--student-col", default="学生",
        help="Excel 中学生姓名列名（默认: 学生）"
    )
    args = parser.parse_args()

    post_process(
        excel_path=args.excel,
        result_dir=args.result_dir,
        output_path=args.output,
        student_col=args.student_col,
    )


if __name__ == "__main__":
    _main()
