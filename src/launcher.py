"""
launcher.py — 三线程池并行调度器（断点续传）
============================================
功能：
  1. 通过 src.config 加载配置，支持 6 个模块独立开关
  2. 扫描 resource/ 目录，匹配标准音频/文本和学生仿读音频
  3. 三线程池分离调度：
     - voice_executor  (1 worker)  — OpenSMILE 语音分析
     - whisper_executor (1 worker) — Whisper 语音转写
     - llm_executor     (400 workers) — LLM 文本比对
  4. Whisper 不等 LLM：转写完成后立即提交 LLM 并处理下一个学生
  5. 断点续传：progress.json 记录每步状态，中断后重启自动跳过已完成步骤
  6. 实时输出：summary.csv 随学生完成即时更新
  7. 8 阶段流水线：
     Phase 1: 标准文件发现 + 特征预计算
     Phase 2: 语音分析（VOICE_ANALYSIS 控制）
     Phase 3: 转写 + LLM（WHISPER_TRANSCRIBE + LLM_COMPARE 控制）
     Phase 4: 等待完成
     Phase 5: 后处理（POST_PROCESS 控制）
     Phase 6: 最终汇总
     Phase 7: 数据完整性预检查（FILTER_PRECHECK 控制）
     Phase 8: 归档 + 错题可视化（ERROR_VISUALIZE 控制）

架构：
  src/config.py → _config（统一配置，含模块开关）
  src/constants.py → 共享常量（评分维度、音频扩展名等）
  src/utils.py → 工具函数（文件查找、报告读写、格式化等）

调度策略：
  - OpenSMILE: ThreadPoolExecutor(max_workers=1)，C++ 库非线程安全
  - Whisper:   ThreadPoolExecutor(max_workers=1)，全局单例模型
  - LLM:       ThreadPoolExecutor(max_workers=400)，纯网络 I/O

断点续传状态机：
  pending → voice:running → voice:done/failed
  pending → text:running → text:transcribed → text:done/failed
"""

# ⚠️ 必须在任何 matplotlib 导入前设置非交互式后端，防止多线程 Tkinter 崩溃
import matplotlib

matplotlib.use("Agg")

import csv
import glob
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# ---- 导入 src 模块 ----
# 添加项目根目录到 path（支持独立运行）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.config import AppConfig
from src.constants import (
    AUDIO_EXTENSIONS,
    SCORE_COLS,
    SUMMARY_COLUMNS,
    VOICE_KEYS,
)
from src.utils import (
    ensure_dir,
    find_single_file,
    format_score_row,
    write_errors_json,
    write_md_report,
)
from src.text_llm import (
    get_whisper_model,
    llm_compare_texts,
    read_standard_text,
    transcribe_only,
)
from src.voice_compare import precompute_standard_features, run_voice_compare

# ==============================================================================
# 全局配置（模块级单例）
# ==============================================================================
_config = AppConfig.load()

# ==============================================================================
# 线程安全基础设施 — 锁 + 全局状态
# ==============================================================================
_progress_lock = threading.Lock()
"""进度文件读写锁（保护 progress_data 和 progress.json）"""

_summary_lock = threading.RLock()
"""汇总 CSV 写入锁（可重入，保护 completed_rows 和 summary.csv）"""

# ---- 全局共享状态（跨 voice / whisper / llm 三个线程池） ----
_cached_std_features: dict = None
"""预计算的标准音频特征（main() 中一次性提取）"""

progress_data: dict = {}
"""进度数据的内存缓存（与 progress.json 同步）"""

progress_path: str = ""
"""progress.json 文件路径"""

summary_path: str = ""
"""summary.csv 文件路径"""

completed_rows: list = []
"""已完成学生的汇总行列表（线程安全：通过 _summary_lock 保护）"""

completion_tracker: "CompletionTracker | None" = None
"""学生完成追踪器（voice + text 均 done 时触发汇总写入）"""

# ---- 三个线程池（在 main() 中初始化） ----
voice_executor: ThreadPoolExecutor = None
whisper_executor: ThreadPoolExecutor = None
llm_executor: ThreadPoolExecutor = None


# ==============================================================================
# 进度文件管理层 — progress.json 的读/写/更新
# ==============================================================================
def load_progress(audio_files_map: dict) -> tuple[dict, set, list]:
    """
    读取进度文件，重建已完成学生列表和汇总行。

    参数:
        audio_files_map: {学生名: 音频路径}，用于清理已不存在的记录

    返回:
        (progress_data, done_set, summary_rows)
        - progress_data: 完整进度字典（含 students 子字典）
        - done_set: voice+text 均 done 的学生名集合
        - summary_rows: 从进度恢复的汇总行列表
    """
    if not os.path.exists(progress_path):
        return {"students": {}}, set(), []

    try:
        with open(progress_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        print("[进度] ⚠️  进度文件损坏，将重新开始。")
        return {"students": {}}, set(), []

    students = data.get("students", {})
    done: set[str] = set()
    rows: list[dict] = []

    for name, state in students.items():
        # 仅当 voice 和 text 均完成后才加入 done_set 和汇总
        if state.get("voice") == "done" and state.get("text") == "done":
            done.add(name)
            row = {"学生": name}
            if "accuracy" in state and state["accuracy"] is not None:
                row["单词准确率"] = float(state["accuracy"])
            for key in SCORE_COLS:
                if key in state and state[key] is not None:
                    row[key] = float(state[key])
            # 计算总成绩（若缺失）
            if "总成绩" not in row and "单词准确率" in row and "语音综合分" in row:
                row["总成绩"] = row["单词准确率"] * 50 + row["语音综合分"] * 0.5
            rows.append(row)

    # 清理进度中已删除的学生记录
    for name in list(students.keys()):
        if name not in audio_files_map:
            del students[name]

    return data, done, rows


def save_progress() -> None:
    """线程安全写入进度文件（外部调用入口，自动加锁）"""
    with _progress_lock:
        _save_progress_nolock()


def update_student_progress(name: str, **kwargs) -> None:
    """
    更新单个学生的进度并原子写入文件。

    全程持有 _progress_lock，保证：
      - dict 突变与文件写入的原子性
      - 多线程并发更新不产生竞态

    参数:
        name: 学生名
        **kwargs: 要更新的字段（如 voice="done", accuracy=0.95）
    """
    global progress_data
    with _progress_lock:
        students = progress_data.setdefault("students", {})
        if name not in students:
            students[name] = {}
        students[name].update(kwargs)
        _save_progress_nolock()


def _save_progress_nolock() -> None:
    """
    写入 progress.json（调用方必须持有 _progress_lock）。

    使用 .tmp + os.replace 实现原子写入，防止中途崩溃损坏文件。
    """
    progress_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    tmp_path = progress_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, progress_path)  # 原子替换（POSIX 语义）


def _build_summary_row(name: str, state: dict) -> dict:
    """
    从进度状态字典构建汇总 CSV 行。

    参数:
        name:  学生名
        state: progress_data["students"][name] 的状态字典

    返回:
        {"学生": ..., "单词准确率": ..., "基频均值": ..., ...}
    """
    row = {"学生": name}
    if "accuracy" in state and state["accuracy"] is not None:
        row["单词准确率"] = float(state["accuracy"])
    for key in VOICE_KEYS:
        if key in state and state[key] is not None:
            row[key] = float(state[key])
    # 总成绩 = 准确率 × 50 + 语音综合分 × 0.5（各占 50%）
    if "单词准确率" in row and "语音综合分" in row:
        row["总成绩"] = row["单词准确率"] * 50 + row["语音综合分"] * 0.5
    return row


def write_summary() -> None:
    """
    线程安全写入汇总 CSV。

    行为：读 completed_rows → 格式化 → 去重（同名取最后）→ 写入 summary.csv
    调用方：_maybe_write_summary() 或 main() 最终汇总

    注意：使用 try_lock 避免 shutdown(wait=False) 后残留线程持锁导致死锁。
    """
    if not _summary_lock.acquire(timeout=10):
        print("[汇总] ⚠️  获取写锁超时，跳过最终写入（数据已由回调实时写入）。")
        return
    try:
        formatted = [format_score_row(r) for r in completed_rows]
        # 去重：同一学生可能被多次更新
        seen: dict[str, dict] = {}
        for r in formatted:
            seen[r["学生"]] = r
        unique = list(seen.values())
        with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(unique)
    finally:
        _summary_lock.release()


def _maybe_write_summary(name: str) -> None:
    """
    当某学生 voice+text 均完成时，更新 completed_rows 并写入 summary.csv。

    被 voice_task 和 _llm_task_with_callback 两处调用。
    由于两处可能并发（不同学生的 voice 和 text 同时完成），_summary_lock 保证安全。
    """
    global progress_data, completed_rows
    state = progress_data.get("students", {}).get(name, {})
    if state.get("voice") == "done" and state.get("text") == "done":
        row = _build_summary_row(name, state)
        with _summary_lock:
            # 去重更新（同名覆盖）
            for i, r in enumerate(completed_rows):
                if r.get("学生") == name:
                    completed_rows[i] = row
                    break
            else:
                completed_rows.append(row)
            write_summary()


# ==============================================================================
# CompletionTracker — 跨线程池完成信号同步
# ==============================================================================
class CompletionTracker:
    """
    线程安全的学生完成追踪器。

    使用场景：
      - voice_task 完成后调用 mark_voice(name)
      - _llm_task_with_callback 完成后调用 mark_text(name)
      - 当 voice_done ∩ text_done 覆盖全部待处理学生时，all_done Event 被置位
      - main() 主线程通过 all_done.wait() 阻塞等待
      - 模块关闭时使用 mark_voice_bulk() / mark_text_bulk() 批量标记
    """

    def __init__(self, total: int):
        """
        参数:
            total: 待处理学生总数
        """
        self.voice_done: set[str] = set()
        self.text_done: set[str] = set()
        self._lock = threading.Lock()
        self.all_done = threading.Event()
        self.total = total
        # total=0 时直接置位，避免 main() 阻塞等待零学生
        if total == 0:
            self.all_done.set()

    def mark_voice(self, name: str) -> None:
        """标记某学生语音分析完成"""
        with self._lock:
            self.voice_done.add(name)
            self._maybe_set()

    def mark_text(self, name: str) -> None:
        """标记某学生文字分析完成"""
        with self._lock:
            self.text_done.add(name)
            self._maybe_set()

    def mark_voice_bulk(self, names: list[str]) -> None:
        """
        批量标记多名学生语音分析完成。
        模块关闭时使用，一次性标记所有待处理学生，防止 all_done 死锁。
        """
        with self._lock:
            for name in names:
                self.voice_done.add(name)
            self._maybe_set()

    def mark_text_bulk(self, names: list[str]) -> None:
        """
        批量标记多名学生文字分析完成。
        模块关闭时使用，一次性标记所有待处理学生，防止 all_done 死锁。
        """
        with self._lock:
            for name in names:
                self.text_done.add(name)
            self._maybe_set()

    def _maybe_set(self) -> None:
        """检查是否所有学生都已 voice+text 双完成"""
        if len(self.voice_done & self.text_done) >= self.total:
            self.all_done.set()


# ==============================================================================
# 三线程池任务函数
# ==============================================================================
def voice_task(
    name: str,
    audio_path: str,
    out_dir: str,
) -> None:
    """
    OpenSMILE 语音分析任务（运行在 voice_executor，固定 1 worker）。

    流程：
      1. 检查断点（voice=done 则跳过）
      2. 调用 run_voice_compare()（使用预计算的标准音频特征缓存）
      3. 更新进度 → 标记 tracker → 检查汇总写入

    参数:
        name:       学生名
        audio_path: 仿读音频路径
        out_dir:    输出目录（result/{学生名}/）
    """
    global completion_tracker

    # 断点续传：语音已完成则跳过
    with _progress_lock:
        state = progress_data.get("students", {}).get(name, {})
    if state.get("voice") == "done":
        print(f"  [Voice] {name} 已完成，跳过。")
        completion_tracker.mark_voice(name)
        return

    print(f"  [Voice] {name} 开始分析 ...")
    update_student_progress(name, voice="running")

    try:
        voice_out_img = os.path.join(out_dir, "voice_comparison_report.png")
        _, scores = run_voice_compare(
            standard_audio_path=None,
            imitation_audio_path=audio_path,
            output_img_path=voice_out_img,
            standard_features=_cached_std_features,
        )

        # 构建进度更新（含所有评分维度）
        update: dict = {"voice": "done"}
        for key in VOICE_KEYS:
            val = float(scores[key])
            update[key] = 0.0 if (val != val) else val  # NaN → 0
        update_student_progress(name, **update)
        print(f"  [Voice] {name} 完成。")
    except Exception as e:
        print(f"  [Voice] {name} 失败: {e}")
        update_student_progress(name, voice="failed")

    # 通知 tracker + 检查该学生是否 voice+text 均完成
    completion_tracker.mark_voice(name)
    _maybe_write_summary(name)


def whisper_loop(
    pending_students: list[tuple[str, str]],
    standard_text: str,
    out_base_dir: str,
) -> None:
    """
    Whisper 转写循环（运行在 whisper_executor 的唯一线程中）。

    核心设计：
      - 顺序处理所有学生（单线程，全局共享 Whisper 模型无需加锁）
      - 每个学生转写完成后立即提交 LLM 任务（不等结果）
      - 立即循环处理下一个学生 → Whisper 不空转

    断点续传：
      - text="done"：跳过
      - text="transcribed"：直接提交 LLM（Whisper 已完成）
      - 其他：重新转写

    参数:
        pending_students: [(学生名, 音频路径), ...]
        standard_text:    标准文本文件路径
        out_base_dir:     输出根目录（result/）
    """
    global completion_tracker

    for name, audio_path in pending_students:
        with _progress_lock:
            state = progress_data.get("students", {}).get(name, {})
        text_state = state.get("text", "pending")

        # ---- 已完成：跳过 ----
        if text_state == "done":
            print(f"  [Whisper] {name} 文字分析已完成，跳过。")
            completion_tracker.mark_text(name)
            _maybe_write_summary(name)
            continue

        # ---- 已转写，仅重跑 LLM ----
        if text_state == "transcribed":
            print(f"  [Whisper] {name} 已转写，直接提交 LLM ...")
            llm_executor.submit(
                _llm_task_with_callback, name, standard_text, out_base_dir
            )
            continue

        # ---- 执行 Whisper 转写 ----
        print(f"  [Whisper] {name} 开始转写 ...")
        update_student_progress(name, text="running")

        try:
            # 调用全局单例 Whisper 模型（单线程运行，天然互斥）
            transcribed_text = transcribe_only(
                audio_path, _config.whisper.model_name
            )
            # ⚠️ 关键：将转写文本存入进度，供 LLM 回调读取
            update_student_progress(
                name, text="transcribed", transcribed_text=transcribed_text
            )
            print(f"  [Whisper] {name} 转写完成 ({len(transcribed_text)} 字符)。")
        except Exception as e:
            print(f"  [Whisper] {name} 转写失败: {e}")
            update_student_progress(name, text="failed")
            completion_tracker.mark_text(name)
            _maybe_write_summary(name)
            continue

        # ---- 提交 LLM 比对（不等待！立即循环处理下一个学生）----
        llm_executor.submit(
            _llm_task_with_callback, name, standard_text, out_base_dir
        )

    print("  [Whisper] 全部学生转写任务已调度完毕。")


def _llm_task_with_callback(
    name: str,
    standard_text_path: str,
    out_base_dir: str,
) -> None:
    """
    LLM 比对任务（运行在 llm_executor）。

    流程：
      1. 从 progress_data 读取 whisper_loop 存储的 transcribed_text
      2. 调用 llm_compare_texts() 进行比对（返回 report, accuracy, errors_data）
      3. 保存 Markdown 报告和结构化错误 JSON 到 result/{name}/
      4. 更新进度 → 标记 tracker → 检查汇总写入

    参数:
        name:               学生名
        standard_text_path: 标准文本文件路径
        out_base_dir:       输出根目录（result/）
    """
    global completion_tracker

    try:
        # 读取标准文本
        standard_text_val = read_standard_text(standard_text_path)

        # 从进度中获取 Whisper 已保存的转写文本（持锁读取）
        with _progress_lock:
            transcribed_text = (
                progress_data.get("students", {})
                .get(name, {})
                .get("transcribed_text", "")
            )

        if not transcribed_text:
            raise RuntimeError(
                "缺少转写文本（progress 中无 transcribed_text），"
                "请确认 whisper_loop 已正确存储"
            )

        print(f"  [LLM] {name} 开始比对 ({len(transcribed_text)} 字符) ...")
        time_start = time.time()

        # llm_compare_texts 返回 3 个值：报告、准确率、结构化错误数据
        report, accuracy, errors_data = llm_compare_texts(
            standard_text_val, transcribed_text
        )
        time_elapsed = time.time() - time_start

        # 保存 Markdown 报告（使用统一写入函数）
        out_dir = os.path.join(out_base_dir, name)
        ensure_dir(out_dir)
        md_path = os.path.join(out_dir, name + ".md")
        write_md_report(
            md_path, transcribed_text, standard_text_val, report,
            model_name=_config.llm.model,
        )

        # 保存结构化错误 JSON（供 error_visualizer 使用）
        errors_json_path = md_path.replace(".md", "_errors.json")
        write_errors_json(errors_json_path, name, float(accuracy), errors_data)

        # 更新进度（text="done" 触发断点续传的跳过逻辑）
        update_student_progress(name, text="done", accuracy=float(accuracy))
        print(
            f"  [LLM] {name} 完成"
            f"（准确率: {accuracy * 100:.2f}%，耗时 {time_elapsed:.1f}s）。"
        )

    except Exception as e:
        print(f"  [LLM] {name} 失败: {e}")
        traceback.print_exc()
        update_student_progress(name, text="failed")

    finally:
        # 无论成败，都标记 text 侧完成并尝试写 summary
        completion_tracker.mark_text(name)
        _maybe_write_summary(name)


# ==============================================================================
# 主入口 — 8 阶段流水线
# ==============================================================================
def main() -> None:
    """
    主调度流程（8 阶段）：
      Phase 0: 加载配置 + 计时初始化
      Phase 1: 预检查（可选，FILTER_PRECHECK 控制）
      Phase 2: 标准文件发现 + 特征预计算
      Phase 2: 语音分析（可选，VOICE_ANALYSIS 控制）
      Phase 3: Whisper 转写 + LLM 比对（可选，WHISPER_TRANSCRIBE + LLM_COMPARE 控制）
      Phase 5: 阻塞等待 CompletionTracker.all_done
      Phase 5: 后处理（可选，POST_PROCESS 控制）
      Phase 6: 最终汇总 + 耗时统计
      Phase 8: 归档 + 错题可视化（可选，ERROR_VISUALIZE 控制）
    """
    global \
        progress_data, \
        progress_path, \
        summary_path, \
        completed_rows, \
        completion_tracker
    global voice_executor, whisper_executor, llm_executor
    global _cached_std_features

    time_total_start = time.time()
    print("=" * 50)
    print("launcher 启动 — 三线程池并行调度器")
    print(f"配置: OpenSMILE 1 | Whisper 1 | LLM {_config.llm.max_concurrency}")
    print(f"模块开关: voice={_config.modules.voice_analysis} "
          f"whisper={_config.modules.whisper_transcribe} "
          f"llm={_config.modules.llm_compare} "
          f"post={_config.modules.post_process} "
          f"visualize={_config.modules.error_visualize}")
    print("=" * 50)

    # ---- 目录初始化（使用配置路径） ----
    base_dir = _config.paths.base_dir
    standard_audio_dir = _config.paths.abs_path(_config.paths.standard_audio_dir)
    standard_text_dir = _config.paths.abs_path(_config.paths.standard_text_dir)
    imitation_audio_dir = _config.paths.abs_path(_config.paths.imitation_audio_dir)
    result_dir = _config.paths.abs_path(_config.paths.result_dir)
    summary_path = os.path.join(result_dir, "summary.csv")
    progress_path = os.path.join(result_dir, "progress.json")

    Path(result_dir).mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Phase 1: 标准文件发现 + 特征预计算
    # =========================================================================
    print("\n[Phase 1] 标准文件发现 ...")

    try:
        standard_audio = find_single_file(standard_audio_dir, AUDIO_EXTENSIONS)
        standard_text = find_single_file(standard_text_dir, "txt")
    except Exception as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"  标准音频: {standard_audio}")
    print(f"  标准文本: {standard_text}")

    # 预计算标准音频特征（仅一次，所有学生复用）
    time_start = time.time()
    _cached_std_features = precompute_standard_features(standard_audio)
    time_precompute = time.time() - time_start
    print(f"  标准音频特征预计算完成（耗时 {time_precompute:.1f}s）")

    # ---- 扫描仿读音频 ----
    imitation_files: list[str] = []
    for ext in AUDIO_EXTENSIONS:
        imitation_files.extend(
            glob.glob(os.path.join(imitation_audio_dir, f"*.{ext}"))
        )
    imitation_files = [
        f for f in imitation_files if "_norm." not in os.path.basename(f)
    ]
    if not imitation_files:
        print("未找到仿读音频文件。")
        sys.exit(0)

    # 构建 {学生名: 音频路径} 映射
    all_students: dict[str, str] = {}
    for f in imitation_files:
        name = os.path.splitext(os.path.basename(f))[0]
        if "_norm" in name:
            continue
        all_students[name] = f

    print(f"  找到 {len(all_students)} 个仿读音频文件")

    # ---- 读取进度（断点续传） ----
    progress_data, done_set, summary_rows = load_progress(all_students)
    completed_rows[:] = summary_rows
    print(
        f"\n进度: 已完成 {len(done_set)} 个学生，"
        f"待处理 {len(all_students) - len(done_set)} 个"
    )

    progress_data["standard_audio"] = os.path.basename(standard_audio)
    progress_data["standard_text"] = os.path.basename(standard_text)
    save_progress()

    # ---- 构建待处理列表 ----
    pending = [
        (name, path) for name, path in all_students.items() if name not in done_set
    ]
    if not pending:
        print("所有学生均已完成。")
        write_summary()
        # 即使全部完成，仍可执行后处理和可视化
        _run_post_phases(result_dir)
        return

    for name, path in pending:
        out_dir = os.path.join(result_dir, name)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        update_student_progress(name, audio_path=path)

    completion_tracker = CompletionTracker(len(pending))

    # ---- 预加载 Whisper 全局单例 ----
    print("\n预加载 Whisper 模型（全局单例）...")
    time_start = time.time()
    get_whisper_model(_config.whisper.model_name)
    time_whisper_load = time.time() - time_start
    print(f"  Whisper 加载完成（耗时 {time_whisper_load:.1f}s）")

    # ---- 启动线程池（固定 3 池） ----
    voice_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="Voice"
    )
    whisper_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="Whisper"
    )
    llm_executor = ThreadPoolExecutor(
        max_workers=_config.llm.max_concurrency, thread_name_prefix="LLM"
    )

    try:
        # =====================================================================
        # Phase 2: 语音分析（可选）
        # =====================================================================
        if _config.modules.voice_analysis:
            print("\n[Phase 3] 提交语音分析任务 ...")
            for name, audio_path in pending:
                out_dir = os.path.join(result_dir, name)
                voice_executor.submit(voice_task, name, audio_path, out_dir)
        else:
            print("\n[Phase 3] 语音分析已跳过（VOICE_ANALYSIS=0）")
            all_pending_names = [name for name, _ in pending]
            completion_tracker.mark_voice_bulk(all_pending_names)
            for name in all_pending_names:
                update_student_progress(name, voice="done")

        # =====================================================================
        # Phase 3: Whisper + LLM（可选）
        # =====================================================================
        if _config.modules.whisper_transcribe and _config.modules.llm_compare:
            print("\n[Phase 4] 提交文字分析任务 ...")
            whisper_executor.submit(
                whisper_loop, pending, standard_text, result_dir
            )
        else:
            skip_reasons = []
            if not _config.modules.whisper_transcribe:
                skip_reasons.append("WHISPER_TRANSCRIBE=0")
            if not _config.modules.llm_compare:
                skip_reasons.append("LLM_COMPARE=0")
            print(f"\n[Phase 4] 文字分析已跳过（{', '.join(skip_reasons)}）")
            all_pending_names = [name for name, _ in pending]
            completion_tracker.mark_text_bulk(all_pending_names)
            for name in all_pending_names:
                update_student_progress(name, text="done")

        # =====================================================================
        # Phase 4: 等待完成
        # =====================================================================
        print("\n[Phase 5] 等待所有任务完成 ...\n")
        completion_tracker.all_done.wait()

    finally:
        print("\n正在关闭线程池 ...")
        # 全部使用 wait=False，避免任何单一任务阻塞整个进程退出
        # ThreadPoolExecutor 线程均为 daemon，进程退出时自动终止
        for pool_name, pool in [
            ("LLM", llm_executor),
            ("Whisper", whisper_executor),
            ("Voice", voice_executor),
        ]:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
                print(f"  {pool_name} 池已关闭。")
            except Exception as e:
                print(f"  {pool_name} 池关闭异常: {e}")

    # =========================================================================
    # Phase 5: 后处理（可选）
    # =========================================================================
    if _config.modules.post_process:
        from src.audio_output import post_process

        print("\n[Phase 6] 后处理：汇总 Excel ...")
        if os.path.exists(summary_path):
            post_process(
                excel_path=summary_path,
                result_dir=result_dir,
                output_path=os.path.join(result_dir, "summary_with_details.xlsx"),
            )
    else:
        print("\n[Phase 6] 后处理已跳过（POST_PROCESS=0）")

    # =========================================================================
    # Phase 6: 最终汇总 + 耗时统计
    # =========================================================================
    print(f"\n[Phase 7] 最终汇总 ...")
    write_summary()
    time_total = time.time() - time_total_start
    print(f"\n{'=' * 50}")
    print("全部完成！计时统计：")
    print(f"  标准音频预分析: {time_precompute:.1f}s")
    print(f"  Whisper 模型加载: {time_whisper_load:.1f}s")
    print(f"  **总耗时: {time_total:.0f}s** ({time_total / 60:.1f}min)")
    print(f"  共 {len(completed_rows)} 条记录")
    print(f"汇总表: {summary_path}\n")

    for row in completed_rows:
        student_name = row.get("学生", "?")
        acc = row.get("单词准确率", "N/A")
        if isinstance(acc, float):
            acc = f"{acc * 100:.1f}%"
        voice_score = row.get("语音综合分", "N/A")
        total_score = row.get("总成绩", "N/A")
        if isinstance(total_score, float):
            total_score = f"{total_score:.2f}"
        print(f"  {student_name}: 准确率={acc}, 语音={voice_score}, 总成绩={total_score}")

    # =========================================================================
    # Phase 7: 数据完整性预检查（可选 — summary.csv 已生成，可做完整对比）
    # =========================================================================
    if _config.modules.filter_precheck:
        from src.filter_name import filter_precheck

        print(f"\n[Phase 7] 数据完整性预检查 ...")
        missing = filter_precheck(
            audio_dir=imitation_audio_dir,
            summary_csv_path=summary_path,
        )
        if missing:
            print(f"  ⚠ 警告: {len(missing)} 个音频文件未出现在 summary 中")
    else:
        print("\n[Phase 7] 预检查已跳过（FILTER_PRECHECK=0）")

    # =========================================================================
    # Phase 8: 归档 + 错题可视化（可选）
    # =========================================================================
    if _config.modules.error_visualize:
        from src.error_visualizer import (
            archive_current_result,
            generate_error_wordclouds,
            generate_progress_curves,
        )

        print(f"\n[Phase 8] 归档 + 错题可视化 ...")
        history_dir = os.path.join(result_dir, "history")
        archive_current_result(summary_path, history_dir)

        error_analysis_dir = os.path.join(result_dir, "error_analysis")
        generate_error_wordclouds(result_dir, error_analysis_dir)
        generate_progress_curves(
            history_dir,
            os.path.join(error_analysis_dir, "progress_curves.png"),
        )
    else:
        print("\n[Phase 8] 错题可视化已跳过（ERROR_VISUALIZE=0）")

    # =========================================================================
    # 清理临时文件
    # =========================================================================
    print("\n清理临时文件 ...")
    _cleanup_temp_files(result_dir)
    print("完成。\n")


def _run_post_phases(result_dir: str) -> None:
    """当所有学生已处理完成时，仍执行后处理、预检查和可视化阶段。"""
    if _config.modules.post_process:
        from src.audio_output import post_process

        print("\n[Phase 5] 后处理：汇总 Excel ...")
        if os.path.exists(summary_path):
            post_process(
                excel_path=summary_path,
                result_dir=result_dir,
                output_path=os.path.join(result_dir, "summary_with_details.xlsx"),
            )

    if _config.modules.filter_precheck:
        from src.filter_name import filter_precheck

        print(f"\n[Phase 7] 数据完整性预检查 ...")
        filter_precheck(
            audio_dir=_config.paths.abs_path(_config.paths.imitation_audio_dir),
            summary_csv_path=summary_path,
        )

    if _config.modules.error_visualize:
        from src.error_visualizer import (
            archive_current_result,
            generate_error_wordclouds,
            generate_progress_curves,
        )

        print(f"\n[Phase 8] 归档 + 错题可视化 ...")
        history_dir = os.path.join(result_dir, "history")
        archive_current_result(summary_path, history_dir)

        error_analysis_dir = os.path.join(result_dir, "error_analysis")
        generate_error_wordclouds(result_dir, error_analysis_dir)
        generate_progress_curves(
            history_dir,
            os.path.join(error_analysis_dir, "progress_curves.png"),
        )


def _cleanup_temp_files(result_dir: str) -> None:
    """清理工作区中的临时文件（_norm.wav 等）。"""
    cleaned = 0
    for root, _dirs, files in os.walk(result_dir):
        for f in files:
            if f.endswith(".tmp") or "_norm." in f:
                try:
                    os.remove(os.path.join(root, f))
                    cleaned += 1
                except OSError:
                    pass
    # 也检查 imitation_audio 目录
    imitation_dir = _config.paths.abs_path(_config.paths.imitation_audio_dir)
    if os.path.isdir(imitation_dir):
        for f in os.listdir(imitation_dir):
            if "_norm." in f:
                try:
                    os.remove(os.path.join(imitation_dir, f))
                    cleaned += 1
                except OSError:
                    pass
    if cleaned:
        print(f"  清理了 {cleaned} 个临时文件")


if __name__ == "__main__":
    main()
