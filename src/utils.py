"""
utils.py — 通用工具函数
========================
跨模块公用的文件查找、目录创建、CSV 格式化、学号提取、
Markdown 报告读写、OpenSMILE 列解析等函数。

所有函数均无副作用（除文件 I/O 外），可被任意模块安全调用。

依赖:
    - src.constants: 共享常量和正则
"""

import csv
import glob
import json
import os
import re
from pathlib import Path
from typing import Sequence

from src.constants import (
    AUDIO_EXTENSIONS_DOT,
    MD_COMPARE_HEADER_PREFIX,
    MD_PATTERN_COMPARE,
    MD_PATTERN_STANDARD,
    MD_PATTERN_TRANSCRIBE,
    MD_STANDARD_HEADER,
    MD_TRANSCRIBE_HEADER,
    OS_KEYWORDS,
    SCORE_COLS,
    STUDENT_ID_PATTERN,
)


# ==============================================================================
# 文件系统工具
# ==============================================================================

def ensure_dir(directory: str) -> None:
    """
    创建目录（含父目录），已存在则跳过。

    参数:
        directory: 目录路径
    """
    Path(directory).mkdir(parents=True, exist_ok=True)


def find_single_file(directory: str, extensions: str | tuple[str, ...]) -> str:
    """
    在目录中查找唯一的指定扩展名文件。

    规则:
      - 支持多扩展名（如 ("mp3", "wav", "m4a")）
      - 自动排除 _norm.wav 等中间生成文件
      - 超过 1 个匹配文件时抛出异常（确保标准文件唯一）

    参数:
        directory:  搜索目录
        extensions: 扩展名字符串或元组（不带点，如 "mp3" 或 ("mp3", "wav")）

    返回:
        唯一匹配文件的完整路径

    异常:
        FileNotFoundError: 无匹配文件
        ValueError: 匹配到多个文件
    """
    if isinstance(extensions, str):
        extensions = (extensions,)
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(directory, f"*.{ext}")))
    # 过滤 OpenSMILE 中间生成的归一化音频
    files = [f for f in files if "_norm." not in os.path.basename(f)]
    if not files:
        raise FileNotFoundError(f"在 {directory} 中没有找到扩展名为 {extensions} 的文件")
    if len(files) > 1:
        raise ValueError(f"在 {directory} 中找到 {len(files)} 个文件，请只保留一个")
    return files[0]


def find_audio_files(directory: str) -> list[str]:
    """
    扫描目录中所有音频文件（排除 _norm 中间文件）。

    参数:
        directory: 搜索目录

    返回:
        音频文件的完整路径列表
    """
    files = []
    for ext in AUDIO_EXTENSIONS_DOT:
        for f in os.listdir(directory):
            if f.lower().endswith(ext) and "_norm." not in f:
                files.append(os.path.join(directory, f))
    return files


# ==============================================================================
# 学生信息提取
# ==============================================================================

def extract_student_id(name: str) -> str | None:
    """
    从字符串中提取 10 位学号。

    参数:
        name: 学生姓名或文件夹名（如 "代祺月-2220241548"）

    返回:
        10 位学号字符串，未找到则返回 None
    """
    match = STUDENT_ID_PATTERN.search(str(name))
    return match.group() if match else None


# ==============================================================================
# CSV / 数据格式化
# ==============================================================================

def format_score_row(row: dict) -> dict:
    """
    格式化汇总行：准确率转为百分比字符串，评分保留两位小数。

    参数:
        row: 原始数值字典

    返回:
        格式化后的字符串字典（用于 CSV 输出）
    """
    formatted = row.copy()
    if "单词准确率" in formatted and isinstance(formatted["单词准确率"], (int, float)):
        formatted["单词准确率"] = f"{formatted['单词准确率'] * 100:.2f}%"
    for col in SCORE_COLS:
        if col in formatted and isinstance(formatted[col], (int, float)):
            formatted[col] = f"{formatted[col]:.2f}"
    return formatted


# ==============================================================================
# Markdown 报告读写
# ==============================================================================

def write_md_report(
    md_path: str,
    transcribed_text: str,
    standard_text: str,
    compare_report: str,
    model_name: str = "",
) -> None:
    """
    将转写文本、标准文本和比对结果写入统一的 Markdown 报告文件。

    写入格式使用 constants.py 中定义的共享标记，确保所有写入者
    和读取者（audio_output）使用相同的节标题。

    参数:
        md_path:          输出 .md 文件路径
        transcribed_text: Whisper 转写文本
        standard_text:    标准文本
        compare_report:   LLM 比对结果（Markdown 格式）
        model_name:       LLM 模型名称（用于比对结果节标题）
    """
    compare_header = f"{MD_COMPARE_HEADER_PREFIX}{model_name}）===**"
    ensure_dir(os.path.dirname(md_path))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(
            f"{MD_TRANSCRIBE_HEADER}\n{transcribed_text}\n\n"
            f"{MD_STANDARD_HEADER}\n{standard_text}\n\n"
            f"{compare_header}\n{compare_report}"
        )


def parse_md_report(md_path: str) -> dict:
    """
    从 Markdown 报告文件中提取转写文本、标准文本和比对结果三节。

    参数:
        md_path: .md 报告文件路径

    返回:
        {"transcribe": str, "standard": str, "compare": str}
        某节不存在时对应值为空字符串
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    transcribe_match = MD_PATTERN_TRANSCRIBE.search(content)
    standard_match = MD_PATTERN_STANDARD.search(content)
    compare_match = MD_PATTERN_COMPARE.search(content)

    return {
        "transcribe": transcribe_match.group(1).strip() if transcribe_match else "",
        "standard": standard_match.group(1).strip() if standard_match else "",
        "compare": compare_match.group(1).strip() if compare_match else "",
    }


# ==============================================================================
# OpenSMILE 特征列解析
# ==============================================================================

def extract_opensmile_columns(feat_df) -> dict:
    """
    从 OpenSMILE ComParE 2016 LLD 特征 DataFrame 中定位 7 个关键列。

    消除 voice_compare.py 中 precompute_standard_features() 和
    run_voice_compare() 两处重复的列解析逻辑。

    参数:
        feat_df: opensmile.Smile.process_file() 返回的 DataFrame

    返回:
        {
            "f0_col": str,       # 基频列名
            "voicing_col": str,  # 清浊音判断列名
            "energy_col": str,   # 能量列名
            "centroid_col": str, # 谱质心列名
            "jitter_col": str,   # Jitter 列名
            "shimmer_col": str,  # Shimmer 列名
            "hnr_col": str,      # HNR 列名
        }
    """
    all_cols = feat_df.columns.tolist()
    # OS_KEYWORDS 顺序: F0, voicing, energy, centroid, jitter, shimmer, HNR
    return {
        "f0_col": _find_col(all_cols, OS_KEYWORDS[0]),
        "voicing_col": _find_col(all_cols, OS_KEYWORDS[1]),
        "energy_col": _find_col(all_cols, OS_KEYWORDS[2]),
        "centroid_col": _find_col(all_cols, OS_KEYWORDS[3]),
        "jitter_col": _find_col(all_cols, OS_KEYWORDS[4]),
        "shimmer_col": _find_col(all_cols, OS_KEYWORDS[5]),
        "hnr_col": _find_col(all_cols, OS_KEYWORDS[6]),
    }


def _find_col(all_cols: list[str], keyword: str) -> str:
    """在列名列表中查找包含关键词的列名，不存在时抛出 ValueError。"""
    matches = [c for c in all_cols if keyword in c]
    if not matches:
        raise ValueError(f"OpenSMILE 特征中未找到包含 '{keyword}' 的列。可用列: {all_cols}")
    return matches[0]


# ==============================================================================
# JSON 错误数据读写
# ==============================================================================

def write_errors_json(
    json_path: str,
    student_name: str,
    accuracy: float,
    errors_by_category: dict,
    timestamp: str = "",
) -> None:
    """
    将结构化错误数据保存为 JSON 文件（供 error_visualizer 使用）。

    参数:
        json_path:          输出 JSON 文件路径
        student_name:       学生标识
        accuracy:           单词准确率 [0.0, 1.0]
        errors_by_category: 按类型分类的错误词列表
                            {"replace": [...], "insert": [...], "delete": [...]}
        timestamp:          ISO 格式时间戳，为空则自动生成
    """
    from datetime import datetime

    if not timestamp:
        timestamp = datetime.now().isoformat()
    ensure_dir(os.path.dirname(json_path))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "student": student_name,
            "accuracy": accuracy,
            "timestamp": timestamp,
            "errors": errors_by_category,
        }, f, ensure_ascii=False, indent=2)


def read_errors_json(json_path: str) -> dict | None:
    """
    读取结构化错误 JSON 文件。

    参数:
        json_path: _errors.json 文件路径

    返回:
        错误数据字典，文件不存在或格式错误时返回 None
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
