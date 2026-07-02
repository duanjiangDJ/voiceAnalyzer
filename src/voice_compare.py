"""
voice_compare.py — 语音特征对比与可视化模块
==============================================
功能：
  1. 音频归一化：统一采样率至 16kHz，幅度归一化
  2. 声学特征提取：通过 OpenSMILE 提取 ComParE 2016 LLDs 特征集
  3. 多维度评分：基频、能量、Jitter、Shimmer、HNR、谱质心、语速
  4. 可视化报告：生成 3×3 子图的对比图表（PNG）

评分维度（共 8 项）：
  - 基频均值：音高整体水平
  - 基频标准差：语调起伏变化
  - 能量均值：重音与力度
  - Jitter 均值：音高稳定性（频率微扰）
  - Shimmer 均值：音量稳定性（振幅微扰）
  - log HNR 均值：清晰度 vs 气息（谐噪比）
  - 谱质心均值：音色明亮度
  - 语速：音节速率估算

依赖：
  - opensmile: ComParE 2016 声学特征提取
  - librosa + soundfile: 音频加载与写入
  - numpy: 数值计算
  - matplotlib: 可视化绑图
  - src.utils: extract_opensmile_columns 函数（消除列解析重复）
  - src.constants: OS_KEYWORDS、AUDIO_EXTENSIONS 共享常量
"""

import os
import time

import librosa
import matplotlib.pyplot as plt
import numpy as np
import opensmile
import soundfile as sf

from src.constants import AUDIO_EXTENSIONS, OS_KEYWORDS
from src.utils import extract_opensmile_columns

# ---- Matplotlib 全局配置 ----
# 设置中文字体（优先 SimHei，回退 DejaVu Sans）
plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
# 解决负号显示异常
plt.rcParams["axes.unicode_minus"] = False


# ==============================================================================
# 音频预处理 — 归一化
# ==============================================================================
def normalize_audio(file_path: str, target_sr: int = 16000) -> str:
    """
    将音频归一化：统一采样率 → 单声道 → 幅度归一化 → 存为 WAV。

    处理流程：
      1. librosa 加载音频（重采样至 target_sr，转为单声道）
      2. 幅度归一化：除以最大绝对值 × 0.95（留 5% 裕量防削波）
      3. soundfile 写入临时 WAV 文件（路径 = 原路径 + '_norm.wav'）

    参数:
        file_path: 原始音频路径
        target_sr:  目标采样率（默认 16000 Hz）

    返回:
        归一化后的 WAV 文件路径（调用方负责清理）
    """
    # 加载音频
    y, sr = librosa.load(file_path, sr=target_sr, mono=True)
    # 幅度归一化（峰值 = 0.95）
    y = y / (np.max(np.abs(y)) + 1e-8) * 0.95
    # 输出至临时文件
    out_path = file_path + "_norm.wav"
    sf.write(out_path, y, target_sr)
    return out_path


# ==============================================================================
# 语速估算 — 基于基频跳变检测
# ==============================================================================
def estimate_syllable_rate(f0_sequence: np.ndarray, frame_shift: float = 0.01) -> float:
    """
    通过基频轨迹的跳变次数估算音节速率。

    原理：音节边界通常伴随基频突变（清浊切换、重音等）。
          统计相邻帧基频差 > 10Hz 的跳变次数，除以总时长得到每秒音节数。

    参数:
        f0_sequence:  基频时间序列（OpenSMILE F0final 列）
        frame_shift: 帧移（秒），ComParE 2016 LLDs 默认 0.01s

    返回:
        每秒音节数（float），若输入无效则返回 0
    """
    f0 = f0_sequence.copy()
    f0[np.isnan(f0)] = 0  # 将 NaN 替换为 0
    diff = np.abs(np.diff(f0))  # 相邻帧基频差
    jump_count = np.sum(diff > 10)  # 跳变次数（阈值 10Hz）
    total_duration = len(f0) * frame_shift
    return jump_count / total_duration if total_duration > 0 else 0


# ==============================================================================
# 相似度评分 — 指数衰减映射
# ==============================================================================
def calc_score(standard_value: float, imitation_value: float, scale: float = 1.0) -> float:
    """
    基于相对差异的指数衰减评分。

    公式：
      rel_diff = |imitation_value - standard_value| / max(|standard_value|, 1e-6)
      score    = 100 * exp(-scale * rel_diff)

    参数:
        standard_value:  标准音频的特征值
        imitation_value: 仿读音频的特征值
        scale:           衰减系数（默认 1.0，越大越严格）

    返回:
        0~100 之间的相似度分数
    """
    denom = max(abs(standard_value), 1e-6)  # 防止除零
    rel_diff = abs(imitation_value - standard_value) / denom
    score = 100 * np.exp(-scale * rel_diff)
    return max(0, min(100, score))  # 钳制至 [0, 100]


# ==============================================================================
# 标准音频预分析 — 提取一次，多次复用
# ==============================================================================
def precompute_standard_features(standard_audio_path: str) -> dict:
    """
    预提取标准音频的 OpenSMILE 特征。

    只需调用一次，后续所有 voice_task 复用返回的特征数据，
    避免对同一标准音频反复执行归一化+特征提取。

    参数:
        standard_audio_path: 标准音频文件路径

    返回:
        特征字典，包含 keys: f0, voicing, energy, centroid, jitter,
        shimmer, hnr, progress, rate
    """
    print("[语音对比] 预分析标准音频（仅一次）...")
    t0 = time.time()

    # 归一化 → 提取特征 → 清理临时文件
    std_norm = normalize_audio(standard_audio_path)
    try:
        smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.ComParE_2016,
            feature_level=opensmile.FeatureLevel.LowLevelDescriptors,
        )
        feat_std = smile.process_file(std_norm)
    finally:
        if os.path.exists(std_norm):
            os.remove(std_norm)

    # 使用共享函数提取关键列（替代重复的列解析代码）
    cols = extract_opensmile_columns(feat_std)

    n_std = feat_std.shape[0]
    cached = {
        "f0": feat_std[cols["f0_col"]].values,
        "voicing": feat_std[cols["voicing_col"]].values > 0.5,
        "energy": feat_std[cols["energy_col"]].values,
        "centroid": feat_std[cols["centroid_col"]].values,
        "jitter": feat_std[cols["jitter_col"]].values,
        "shimmer": feat_std[cols["shimmer_col"]].values,
        "hnr": feat_std[cols["hnr_col"]].values,
        "progress": np.linspace(0, 1, n_std),
        "rate": estimate_syllable_rate(feat_std[cols["f0_col"]].values),
        "n_frames": n_std,
    }

    elapsed = time.time() - t0
    print(f"[语音对比] 标准音频预分析完成（耗时 {elapsed:.1f}s）。")
    return cached


# ==============================================================================
# 核心对比函数 — 特征提取 + 评分 + 可视化
# ==============================================================================
def run_voice_compare(
    standard_audio_path: str = None,
    imitation_audio_path: str = None,
    output_img_path: str = "",
    standard_features: dict = None,
) -> tuple[str, dict]:
    """
    对比标准音频与仿读音频，生成多维度评分和可视化报告。

    流程：
      1. 归一化仿读音频 → 临时 WAV（标准音频使用预计算缓存）
      2. OpenSMILE 提取 ComParE 2016 LLDs 特征
      3. 清理临时 WAV 文件
      4. 提取 7 个关键声学列 + 语速估算
      5. 绘制 3×3 对比子图
      6. 计算 8 维度得分 + 综合分

    参数:
        standard_audio_path:  标准音频文件路径（用于向后兼容）
        imitation_audio_path: 仿读音频文件路径
        output_img_path:      输出 PNG 图片路径
        standard_features:    预计算的标准音频特征（由 precompute_standard_features 返回）。
                              传入后跳过标准音频的归一化和特征提取。

    返回:
        (output_img_path, scores_dict)
    """
    # ---- 1. 加载标准特征（预计算或实时提取） ----
    if standard_features is not None:
        # 使用预计算缓存，跳过标准音频处理
        feat_std_values = standard_features
    elif standard_audio_path is not None:
        # 向后兼容：实时提取标准特征
        feat_std_values = precompute_standard_features(standard_audio_path)
    else:
        raise ValueError("必须提供 standard_audio_path 或 standard_features")

    # ---- 2. 仿读音频归一化 + 特征提取 ----
    imit_norm = normalize_audio(imitation_audio_path)
    try:
        smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.ComParE_2016,
            feature_level=opensmile.FeatureLevel.LowLevelDescriptors,
        )
        feat_imit = smile.process_file(imit_norm)
    finally:
        if os.path.exists(imit_norm):
            os.remove(imit_norm)

    # ---- 3. 从缓存加载标准特征 + 提取仿读特征 ----
    # 标准特征（来自预计算缓存，无需再次 OpenSMILE 处理）
    f0_std = feat_std_values["f0"]
    voiced_std = feat_std_values["voicing"]
    energy_std = feat_std_values["energy"]
    centroid_std = feat_std_values["centroid"]
    jitter_std = feat_std_values["jitter"]
    shimmer_std = feat_std_values["shimmer"]
    hnr_std = feat_std_values["hnr"]
    progress_std = feat_std_values["progress"]
    rate_std = feat_std_values["rate"]

    # 仿读特征（从 DataFrame 提取，使用共享函数消除重复列解析）
    cols = extract_opensmile_columns(feat_imit)

    n_imit = feat_imit.shape[0]
    progress_imit = np.linspace(0, 1, n_imit)

    f0_imit = feat_imit[cols["f0_col"]].values
    energy_imit = feat_imit[cols["energy_col"]].values
    centroid_imit = feat_imit[cols["centroid_col"]].values
    jitter_imit = feat_imit[cols["jitter_col"]].values
    shimmer_imit = feat_imit[cols["shimmer_col"]].values
    hnr_imit = feat_imit[cols["hnr_col"]].values
    voiced_imit = feat_imit[cols["voicing_col"]].values > 0.5
    rate_imit = estimate_syllable_rate(f0_imit)

    # ---- 6. 绘制 3×3 对比子图 ----
    plt.figure(figsize=(16, 12))

    # 子图 1: 基频轨迹 — 音高与语调
    ax1 = plt.subplot(3, 3, 1)
    ax1.plot(progress_std * 100, f0_std, label="标准", alpha=0.8)
    ax1.plot(progress_imit * 100, f0_imit, label="仿读", alpha=0.8)
    ax1.set_xlabel("播放进度 (%)")
    ax1.set_ylabel("基频 (Hz)")
    ax1.set_title("基频轨迹 - 音高与语调")
    ax1.legend()

    # 子图 2: 能量轨迹 — 重音与力度
    ax2 = plt.subplot(3, 3, 2)
    ax2.plot(progress_std * 100, energy_std, label="标准", alpha=0.8)
    ax2.plot(progress_imit * 100, energy_imit, label="仿读", alpha=0.8)
    ax2.set_xlabel("播放进度 (%)")
    ax2.set_ylabel("RMS 能量")
    ax2.set_title("能量轨迹 - 重音与力度")
    ax2.legend()

    # 子图 3: 谱质心 — 音色明亮度
    ax3 = plt.subplot(3, 3, 3)
    ax3.plot(progress_std * 100, centroid_std, label="标准", alpha=0.8)
    ax3.plot(progress_imit * 100, centroid_imit, label="仿读", alpha=0.8)
    ax3.set_xlabel("播放进度 (%)")
    ax3.set_ylabel("谱质心 (Hz)")
    ax3.set_title("谱质心 - 音色明亮度")
    ax3.legend()

    # 子图 4: Jitter — 音高稳定性
    ax4 = plt.subplot(3, 3, 4)
    ax4.plot(progress_std * 100, jitter_std, label="标准", alpha=0.8)
    ax4.plot(progress_imit * 100, jitter_imit, label="仿读", alpha=0.8)
    ax4.set_xlabel("播放进度 (%)")
    ax4.set_ylabel("Jitter")
    ax4.set_title("频率微扰 (Jitter) - 音高稳定性")
    ax4.legend()

    # 子图 5: Shimmer — 音量稳定性
    ax5 = plt.subplot(3, 3, 5)
    ax5.plot(progress_std * 100, shimmer_std, label="标准", alpha=0.8)
    ax5.plot(progress_imit * 100, shimmer_imit, label="仿读", alpha=0.8)
    ax5.set_xlabel("播放进度 (%)")
    ax5.set_ylabel("Shimmer (dB)")
    ax5.set_title("振幅微扰 (Shimmer) - 音量稳定性")
    ax5.legend()

    # 子图 6: HNR — 清晰度 vs 气息
    ax6 = plt.subplot(3, 3, 6)
    ax6.plot(progress_std * 100, hnr_std, label="标准", alpha=0.8)
    ax6.plot(progress_imit * 100, hnr_imit, label="仿读", alpha=0.8)
    ax6.set_xlabel("播放进度 (%)")
    ax6.set_ylabel("log HNR")
    ax6.set_title("谐噪比 (HNR) - 清晰度 vs 气息")
    ax6.legend()

    # 子图 7: 语速对比（柱状图）
    ax7 = plt.subplot(3, 3, 7)
    ax7.bar(["标准", "仿读"], [rate_std, rate_imit], color=["#1f77b4", "#ff7f0e"])
    ax7.set_ylabel("音节/秒")
    ax7.set_title("估算语速")

    # 子图 8: 基频分布（有声段直方图）
    ax8 = plt.subplot(3, 3, 8)
    ax8.hist(f0_std[voiced_std], bins=30, alpha=0.5, label="标准", density=True)
    ax8.hist(f0_imit[voiced_imit], bins=30, alpha=0.5, label="仿读", density=True)
    ax8.set_xlabel("基频 (Hz)")
    ax8.set_ylabel("概率密度")
    ax8.set_title("基频分布 (有声帧)")
    ax8.legend()

    # ---- 7. 多维度得分计算 ----
    # 注意：谱质心仅在有声帧上计算均值
    std_centroid_voiced = centroid_std[voiced_std]
    imit_centroid_voiced = centroid_imit[voiced_imit]

    # 各维度均值/标准差汇总
    f0_mean_std, f0_mean_imit = np.nanmean(f0_std), np.nanmean(f0_imit)
    f0_std_std, f0_std_imit = np.nanstd(f0_std), np.nanstd(f0_imit)
    energy_mean_std, energy_mean_imit = np.nanmean(energy_std), np.nanmean(energy_imit)
    jitter_mean_std, jitter_mean_imit = np.nanmean(jitter_std), np.nanmean(jitter_imit)
    shimmer_mean_std, shimmer_mean_imit = np.nanmean(shimmer_std), np.nanmean(shimmer_imit)
    hnr_mean_std, hnr_mean_imit = np.nanmean(hnr_std), np.nanmean(hnr_imit)
    centroid_mean_std = (
        np.nanmean(std_centroid_voiced) if len(std_centroid_voiced) > 0 else np.nan
    )
    centroid_mean_imit = (
        np.nanmean(imit_centroid_voiced) if len(imit_centroid_voiced) > 0 else np.nan
    )

    # 对每个维度计算相似度分数（0~100）
    scores = {
        "基频均值": calc_score(f0_mean_std, f0_mean_imit),
        "基频标准差": calc_score(f0_std_std, f0_std_imit),
        "能量均值": calc_score(energy_mean_std, energy_mean_imit),
        "Jitter均值": calc_score(jitter_mean_std, jitter_mean_imit),
        "Shimmer均值": calc_score(shimmer_mean_std, shimmer_mean_imit),
        "log HNR均值": calc_score(hnr_mean_std, hnr_mean_imit),
        "谱质心均值": calc_score(centroid_mean_std, centroid_mean_imit),
        "语速": calc_score(rate_std, rate_imit),
    }
    avg_score = np.mean(list(scores.values()))  # 8 维度算术平均

    # ---- 8. 子图 9: 得分汇总（水平柱状图） ----
    ax9 = plt.subplot(3, 3, 9)
    dims = list(scores.keys())
    vals = list(scores.values())
    # 颜色编码：≥80 绿色（优秀），60~79 橙色（一般），<60 红色（需改进）
    colors = [
        "#2ca02c" if v >= 80 else "#ff7f0e" if v >= 60 else "#d62728" for v in vals
    ]
    bars = ax9.barh(dims, vals, color=colors)
    ax9.set_xlim(0, 100)
    ax9.set_xlabel("分数 (0-100)")
    ax9.set_title(f"各维度模仿相似度得分 (综合得分：{avg_score:.1f})")
    for bar, v in zip(bars, vals):
        ax9.text(
            bar.get_width() + 1,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.0f}",
            va="center",
        )

    # ---- 9. 保存与清理 ----
    plt.tight_layout()
    plt.savefig(output_img_path, dpi=150)
    plt.close()  # 关闭图形释放内存（多线程环境下尤其重要）

    scores["语音综合分"] = avg_score
    print(f"[语音对比] 图表已保存: {output_img_path}")
    return output_img_path, scores


# ==============================================================================
# 直接运行兼容
# ==============================================================================
if __name__ == "__main__":
    std_audio = "standard.mp3"
    imit_audio = "imitation.mp3"
    output = "voice_comparison_report.png"
    if os.path.exists(std_audio) and os.path.exists(imit_audio):
        run_voice_compare(std_audio, imit_audio, output)
    else:
        print("请在标准/仿读音频存在时直接运行，或通过接口调用。")
