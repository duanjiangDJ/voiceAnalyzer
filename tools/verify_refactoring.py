"""
verify_refactoring.py — 重构后综合验证脚本
============================================
对 src/ 下所有模块进行全面验证：导入、常量、配置、工具函数、
模块 API、模块开关、文件 I/O、错误可视化、断点续传模拟。

用法:
    python tools/verify_refactoring.py

退出码:
    0 = 全部通过
    1 = 至少一项失败
"""

import csv
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime

# 确保项目根目录在 path 中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

# ==============================================================================
# 测试框架
# ==============================================================================
_passed = 0
_failed = 0
_skipped = 0


def test(name: str) -> None:
    """装饰器式的测试分组标记（仅输出分组标题）。"""
    print(f"\n{'─' * 55}")
    print(f"  {name}")
    print(f"{'─' * 55}")


def check(desc: str, condition: bool) -> None:
    """断言一个条件，记录通过/失败。"""
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✅ {desc}")
    else:
        _failed += 1
        print(f"  ❌ {desc}")


def skip(desc: str) -> None:
    """跳过此项测试。"""
    global _skipped
    _skipped += 1
    print(f"  ⏭ {desc}（跳过）")


def check_equal(desc: str, actual, expected) -> None:
    """断言两值相等。"""
    ok = actual == expected
    if not ok:
        print(f"     期望: {expected!r}")
        print(f"     实际: {actual!r}")
    check(desc, ok)


def check_contains(desc: str, container, item) -> None:
    """断言容器包含某项。"""
    check(desc, item in container)


def run_section(title: str, func) -> None:
    """运行一个测试分组，捕获异常。"""
    test(title)
    try:
        func()
    except Exception as e:
        global _failed
        _failed += 1
        print(f"  ❌ 异常: {e}")
        traceback.print_exc()


# ==============================================================================
# 第 1 组：模块导入
# ==============================================================================
def test_imports():
    """验证所有 src 模块可正常导入。"""

    # 基础层（零依赖）
    from src.constants import (  # noqa: F401
        VOICE_KEYS, SCORE_COLS, SUMMARY_COLUMNS, AUDIO_EXTENSIONS,
        AUDIO_EXTENSIONS_DOT, OS_KEYWORDS, ERROR_CATEGORIES,
        ERROR_TYPE_REPLACE, ERROR_TYPE_INSERT, ERROR_TYPE_DELETE,
        WORDCLOUD_COLORS, STUDENT_ID_PATTERN,
        MD_TRANSCRIBE_HEADER, MD_STANDARD_HEADER, MD_COMPARE_HEADER_PREFIX,
        MD_PATTERN_TRANSCRIBE, MD_PATTERN_STANDARD, MD_PATTERN_COMPARE,
    )
    check("导入 src/constants.py", True)

    from src.config import AppConfig, LLMConfig, ModuleSwitches, PathConfig, WhisperConfig
    check("导入 src/config.py", True)

    from src.utils import (
        ensure_dir, find_single_file, find_audio_files, extract_student_id,
        format_score_row, write_md_report, parse_md_report,
        extract_opensmile_columns, write_errors_json, read_errors_json,
    )
    check("导入 src/utils.py (10 functions)", True)

    # 分析模块
    from src.filter_name import filter_precheck
    check("导入 src/filter_name.py", True)

    from src.audio_output import post_process
    check("导入 src/audio_output.py", True)

    from src.error_visualizer import (
        generate_error_wordclouds, generate_progress_curves, archive_current_result,
    )
    check("导入 src/error_visualizer.py", True)

    from src import launcher as launcher_mod  # noqa: F401
    check("导入 src/launcher.py", True)


# ==============================================================================
# 第 2 组：常量验证
# ==============================================================================
def test_constants():
    """验证所有常量的值和一致性。"""
    from src import constants as c

    # VOICE_KEYS: 9 项（8 维度 + 综合分）
    check_equal("VOICE_KEYS 数量", len(c.VOICE_KEYS), 9)
    check_contains("VOICE_KEYS 含综合分", c.VOICE_KEYS, "语音综合分")

    # SCORE_COLS: VOICE_KEYS + 总成绩
    check_equal("SCORE_COLS 数量", len(c.SCORE_COLS), 10)
    check_contains("SCORE_COLS 含总成绩", c.SCORE_COLS, "总成绩")

    # SUMMARY_COLUMNS: 学生 + 准确率 + SCORE_COLS
    check_equal("SUMMARY_COLUMNS 数量", len(c.SUMMARY_COLUMNS), 12)
    check_equal("SUMMARY_COLUMNS[0]", c.SUMMARY_COLUMNS[0], "学生")

    # AUDIO_EXTENSIONS: 6 种
    check_equal("AUDIO_EXTENSIONS 数量", len(c.AUDIO_EXTENSIONS), 6)
    check_equal("AUDIO_EXTENSIONS_DOT 数量", len(c.AUDIO_EXTENSIONS_DOT), 6)
    check("AUDIO_EXTENSIONS_DOT 带点", all(e.startswith(".") for e in c.AUDIO_EXTENSIONS_DOT))

    # OS_KEYWORDS: 7 个
    check_equal("OS_KEYWORDS 数量", len(c.OS_KEYWORDS), 7)

    # ERROR_CATEGORIES: 3 类
    check_equal("ERROR_CATEGORIES 数量", len(c.ERROR_CATEGORIES), 3)

    # WORDCLOUD_COLORS: 3 种颜色
    check_equal("WORDCLOUD_COLORS 数量", len(c.WORDCLOUD_COLORS), 3)

    # STUDENT_ID_PATTERN: 匹配 10 位数字
    check("STUDENT_ID_PATTERN 匹配学号", bool(c.STUDENT_ID_PATTERN.search("abc2220241548xyz")))
    check("STUDENT_ID_PATTERN 不匹配短数字",
          not bool(c.STUDENT_ID_PATTERN.fullmatch("12345")))

    # MD 标记一致性
    check("MD_TRANSCRIBE_HEADER 含 ===", "===" in c.MD_TRANSCRIBE_HEADER)
    check("MD_COMPARE_HEADER_PREFIX 含模型",
          "模型" in c.MD_COMPARE_HEADER_PREFIX)

    # 预编译正则
    check("MD_PATTERN_TRANSCRIBE 是 compiled regex",
          hasattr(c.MD_PATTERN_TRANSCRIBE, 'search'))


# ==============================================================================
# 第 3 组：配置加载
# ==============================================================================
def test_config():
    """验证 AppConfig 从 .env 加载正确。"""
    from src.config import AppConfig

    config = AppConfig.load()

    # LLM
    check("LLM api_key 非空", config.llm.api_key != "")
    check("LLM api_base 正确", "deepseek" in config.llm.api_base)
    check("LLM model 非空", config.llm.model != "")
    check("LLM max_concurrency > 0", config.llm.max_concurrency > 0)

    # Whisper
    check("Whisper model_name 非空", config.whisper.model_name != "")

    # Module switches: 所有默认开启
    check("filter_precheck 开启", config.modules.filter_precheck)
    check("voice_analysis 开启", config.modules.voice_analysis)
    check("whisper_transcribe 开启", config.modules.whisper_transcribe)
    check("llm_compare 开启", config.modules.llm_compare)
    check("post_process 开启", config.modules.post_process)
    check("error_visualize 开启", config.modules.error_visualize)

    # Paths
    check("base_dir 非空", config.paths.base_dir != "")
    check("standard_audio_dir 含 resource",
          "resource" in config.paths.standard_audio_dir)
    check("result_dir 含 resource",
          "resource" in config.paths.result_dir)
    check("abs_path 工作",
          config.paths.abs_path("test").endswith("test"))


# ==============================================================================
# 第 4 组：工具函数
# ==============================================================================
def test_utils():
    """验证所有 utils.py 函数行为正确。"""
    from src import utils

    tmpdir = tempfile.mkdtemp(prefix="verify_")

    try:
        # ---- ensure_dir ----
        test_dir = os.path.join(tmpdir, "a", "b", "c")
        utils.ensure_dir(test_dir)
        check("ensure_dir 创建嵌套目录", os.path.isdir(test_dir))
        utils.ensure_dir(test_dir)  # 不抛异常
        check("ensure_dir 幂等", True)

        # ---- extract_student_id ----
        check_equal("extract_student_id 标准格式",
                    utils.extract_student_id("代祺月-2220241548"), "2220241548")
        check_equal("extract_student_id 纯学号",
                    utils.extract_student_id("2220241548"), "2220241548")
        check("extract_student_id 无学号返回 None",
              utils.extract_student_id("no_id_here") is None)
        check("extract_student_id 短数字返回 None",
              utils.extract_student_id("12345") is None)

        # ---- format_score_row ----
        row = {"学生": "test", "单词准确率": 0.8523, "基频均值": 78.5, "语音综合分": 82.3}
        fmt = utils.format_score_row(row)
        check_equal("format_score_row 准确率", fmt["单词准确率"], "85.23%")
        check_equal("format_score_row 基频均值", fmt["基频均值"], "78.50")
        check("format_score_row 保留原名", fmt["学生"] == "test")

        # ---- find_single_file ----
        sd = os.path.join(tmpdir, "single")
        utils.ensure_dir(sd)
        with open(os.path.join(sd, "only.txt"), "w") as f:
            f.write("test")
        found = utils.find_single_file(sd, "txt")
        check("find_single_file 找到唯一文件", "only.txt" in found)

        # 多个文件应抛异常
        with open(os.path.join(sd, "extra.txt"), "w") as f:
            f.write("test")
        try:
            utils.find_single_file(sd, "txt")
            check("find_single_file 多文件抛异常", False)
        except ValueError:
            check("find_single_file 多文件抛异常", True)

        # 无文件应抛异常
        os.remove(os.path.join(sd, "only.txt"))
        os.remove(os.path.join(sd, "extra.txt"))
        try:
            utils.find_single_file(sd, "txt")
            check("find_single_file 无文件抛异常", False)
        except FileNotFoundError:
            check("find_single_file 无文件抛异常", True)

        # ---- write_md_report + parse_md_report round-trip ----
        md_path = os.path.join(tmpdir, "roundtrip.md")
        transcribe = "hello world"
        standard = "hello world"
        compare = "# 比对\n差异: 无"
        utils.write_md_report(md_path, transcribe, standard, compare,
                              model_name="test-model")
        check("write_md_report 文件存在", os.path.exists(md_path))

        parsed = utils.parse_md_report(md_path)
        check_equal("round-trip transcribe", parsed["transcribe"], transcribe)
        check_equal("round-trip standard", parsed["standard"], standard)
        check_equal("round-trip compare", parsed["compare"], compare)

        # 多行内容 round-trip
        utils.write_md_report(md_path, "a\nb\nc", "x\ny\nz", "1\n2\n3",
                              model_name="m")
        parsed2 = utils.parse_md_report(md_path)
        check("round-trip multi-line transcribe",
              parsed2["transcribe"] == "a\nb\nc")
        check("round-trip multi-line standard",
              parsed2["standard"] == "x\ny\nz")

        # ---- write_errors_json + read_errors_json round-trip ----
        err_path = os.path.join(tmpdir, "errors.json")
        errors = {
            "replace": [{"standard": "breeze", "transcribed": "breed"}],
            "insert": ["the"],
            "delete": ["a", "that"],
        }
        utils.write_errors_json(err_path, "test-student", 0.8523, errors)
        check("write_errors_json 文件存在", os.path.exists(err_path))

        readback = utils.read_errors_json(err_path)
        check("read_errors_json 非 None", readback is not None)
        check_equal("read_errors_json student", readback["student"], "test-student")
        check_equal("read_errors_json accuracy", readback["accuracy"], 0.8523)
        check_equal("read_errors_json replace count",
                    len(readback["errors"]["replace"]), 1)

        # 不存在的文件返回 None
        check("read_errors_json 不存在返回 None",
              utils.read_errors_json(os.path.join(tmpdir, "nope.json")) is None)

        # ---- read_errors_json 损坏文件返回 None ----
        with open(os.path.join(tmpdir, "bad.json"), "w") as f:
            f.write("not json{{{")
        check("read_errors_json 损坏返回 None",
              utils.read_errors_json(os.path.join(tmpdir, "bad.json")) is None)

        # ---- find_audio_files ----
        ad = os.path.join(tmpdir, "audio")
        utils.ensure_dir(ad)
        for name in ["test.mp3", "test.wav", "not_audio.txt"]:
            with open(os.path.join(ad, name), "w") as f:
                f.write("fake")
        audio_files = utils.find_audio_files(ad)
        check("find_audio_files 找到 2 个", len(audio_files) == 2)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==============================================================================
# 第 5 组：filter_name 模块
# ==============================================================================
def test_filter_name():
    """验证 filter_precheck API。"""
    from src.filter_name import filter_precheck

    tmpdir = tempfile.mkdtemp(prefix="verify_filter_")

    try:
        # 创建测试数据
        audio_dir = os.path.join(tmpdir, "audio")
        os.makedirs(audio_dir)
        for name in ["代祺月-2220241548", "单丽鑫-2220242310", "古金池-2220243135"]:
            with open(os.path.join(audio_dir, f"{name}.mp3"), "w") as f:
                f.write("fake")

        # summary 只有 2 个学生
        summary_csv = os.path.join(tmpdir, "summary.csv")
        with open(summary_csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["学生", "单词准确率", "语音综合分", "总成绩"])
            w.writerow(["代祺月-2220241548", "85.23%", "78.50", "81.37"])
            w.writerow(["单丽鑫-2220242310", "90.10%", "82.30", "86.20"])

        # 运行预检查
        missing = filter_precheck(
            audio_dir=audio_dir,
            summary_csv_path=summary_csv,
            name_csv="",
            missing_csv="",
        )

        check("filter_precheck 返回 list", isinstance(missing, list))
        check_equal("filter_precheck 缺失 1 个", len(missing), 1)
        check("filter_precheck 缺失古金池", "古金池-2220243135" in missing[0])

        # 路径不存在抛异常
        try:
            filter_precheck(audio_dir="/nonexistent/path", summary_csv_path=summary_csv)
            check("filter_precheck 不存在路径抛异常", False)
        except FileNotFoundError:
            check("filter_precheck 不存在路径抛异常", True)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==============================================================================
# 第 6 组：audio_output 模块
# ==============================================================================
def test_audio_output():
    """验证 post_process API。"""
    from src.audio_output import post_process

    tmpdir = tempfile.mkdtemp(prefix="verify_audio_out_")

    try:
        # 创建 summary Excel
        import pandas as pd
        df = pd.DataFrame({
            "学生": ["代祺月-2220241548", "单丽鑫-2220242310"],
            "单词准确率": ["85.23%", "90.10%"],
            "语音综合分": [78.5, 82.3],
            "总成绩": [81.37, 86.20],
        })
        excel_path = os.path.join(tmpdir, "summary.xlsx")
        df.to_excel(excel_path, index=False, engine="openpyxl")

        # 创建学生结果目录（含 .md 和 .png）
        result_dir = os.path.join(tmpdir, "result")
        for name in ["代祺月-2220241548", "单丽鑫-2220242310"]:
            student_dir = os.path.join(result_dir, name)
            os.makedirs(student_dir)

            # MD report
            md_path = os.path.join(student_dir, f"{name}.md")
            from src.utils import write_md_report
            write_md_report(md_path, f"trans_{name}", f"std_{name}",
                            f"cmp_{name}", model_name="test")

            # PNG placeholder
            with open(os.path.join(student_dir, "voice_comparison_report.png"), "w") as f:
                f.write("fake png")

        # 运行后处理
        output_path = os.path.join(tmpdir, "output.xlsx")
        result = post_process(
            excel_path=excel_path,
            result_dir=result_dir,
            output_path=output_path,
            student_col="学生",
        )

        check("post_process 返回路径", os.path.exists(result))
        check("post_process 输出文件存在", os.path.exists(output_path))

        # 验证输出内容
        df_out = pd.read_excel(output_path, engine="openpyxl")
        check("post_process 新增列存在", "朗读转写文本" in df_out.columns)
        check("post_process 新增列存在", "朗读标准文本" in df_out.columns)
        check("post_process 新增列存在", "比对结果" in df_out.columns)
        check("post_process 新增列存在", "对比图片" in df_out.columns)

        # 检查第 1 行有内容
        check_equal("post_process 转写文本",
                    df_out["朗读转写文本"].iloc[0], "trans_代祺月-2220241548")
        check_equal("post_process 标准文本",
                    df_out["朗读标准文本"].iloc[0], "std_代祺月-2220241548")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==============================================================================
# 第 7 组：error_visualizer 模块
# ==============================================================================
def test_error_visualizer():
    """验证错误可视化模块的公共 API。"""
    from src.error_visualizer import (
        generate_error_wordclouds,
        generate_progress_curves,
        archive_current_result,
    )

    tmpdir = tempfile.mkdtemp(prefix="verify_viz_")

    try:
        # ---- archive_current_result ----
        history_dir = os.path.join(tmpdir, "history")
        summary_csv = os.path.join(tmpdir, "summary.csv")
        with open(summary_csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["学生", "单词准确率", "语音综合分", "总成绩"])
            w.writerow(["test-student", "85.23%", "78.5", "81.37"])

        archived = archive_current_result(summary_csv, history_dir)
        timestamp = datetime.now().strftime("%Y-%m-%d")
        check("archive 文件名含时间戳", timestamp in os.path.basename(archived))
        check("archive 文件存在", os.path.exists(archived))

        # ---- generate_error_wordclouds (wordcloud library test) ----
        # 创建带 errors.json 的学生目录
        result_dir = os.path.join(tmpdir, "result")
        student_dir = os.path.join(result_dir, "test-2220241548")
        os.makedirs(student_dir)

        from src.utils import write_errors_json
        errors = {
            "replace": [{"standard": "breeze", "transcribed": "breed"},
                        {"standard": "freedom", "transcribed": "free"}],
            "insert": ["the", "the", "and"],
            "delete": ["that", "a"],
        }
        write_errors_json(
            os.path.join(student_dir, "test-2220241548_errors.json"),
            "test-2220241548", 0.85, errors,
        )

        output_dir = os.path.join(tmpdir, "output")
        wordcloud_paths = generate_error_wordclouds(result_dir, output_dir)

        # 检查 wordcloud 是否可用
        try:
            import wordcloud  # noqa: F401
            _wc_available = True
        except ImportError:
            _wc_available = False

        if _wc_available:
            check("词云 replace 已生成",
                  "replace" in wordcloud_paths and os.path.exists(wordcloud_paths.get("replace", "")))
            check("词云 insert 已生成",
                  "insert" in wordcloud_paths and os.path.exists(wordcloud_paths.get("insert", "")))
            check("词云 delete 已生成",
                  "delete" in wordcloud_paths and os.path.exists(wordcloud_paths.get("delete", "")))
        else:
            skip("wordcloud 库未安装，改用 bar chart 回退 — 检查输出")

        # ---- generate_progress_curves ----
        # 创建 2 次历史运行数据
        hd = os.path.join(tmpdir, "history")
        os.makedirs(hd, exist_ok=True)
        for i, ts in enumerate(["2026-07-01_120000", "2026-07-02_120000"]):
            csv_path = os.path.join(hd, f"{ts}_summary.csv")
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["学生", "单词准确率", "语音综合分", "总成绩"])
                w.writerow([f"student{i+1}", f"{75+i*5}.00%", f"{70+i*3}", f"{72+i*2}"])

        curve_path = os.path.join(output_dir, "progress_curves.png")
        result = generate_progress_curves(hd, curve_path)
        check("progress_curves 已生成", os.path.exists(result))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==============================================================================
# 第 8 组：completion_tracker 逻辑
# ==============================================================================
def test_completion_tracker():
    """验证 CompletionTracker 批量标记和死锁防止。"""
    from src.launcher import CompletionTracker

    # 正常流程
    tracker = CompletionTracker(total=3)
    tracker.mark_voice("A")
    tracker.mark_voice("B")
    tracker.mark_voice("C")
    check("只有 voice done 未触发", not tracker.all_done.is_set())
    tracker.mark_text("A")
    tracker.mark_text("B")
    tracker.mark_text("C")
    check("全部完成触发 all_done", tracker.all_done.is_set())

    # 批量标记（模块关闭场景）
    tracker2 = CompletionTracker(total=3)
    tracker2.mark_voice_bulk(["A", "B", "C"])
    check("批量 voice done 未触发", not tracker2.all_done.is_set())
    tracker2.mark_text_bulk(["A", "B", "C"])
    check("批量 text done 触发", tracker2.all_done.is_set())

    # 混合场景
    tracker3 = CompletionTracker(total=2)
    tracker3.mark_voice("A")
    tracker3.mark_voice_bulk(["B"])
    tracker3.mark_text("A")
    tracker3.mark_text_bulk(["B"])
    check("混合批量标记触发", tracker3.all_done.is_set())

    # 空列表
    tracker4 = CompletionTracker(total=0)
    check("total=0 直接触发", tracker4.all_done.is_set())


# ==============================================================================
# 第 9 组：模块开关模拟
# ==============================================================================
def test_module_switches():
    """验证 ModuleSwitches 各个开关可独立设置。"""
    from src.config import ModuleSwitches

    # 默认全开
    ms = ModuleSwitches()
    check("默认 filter_precheck", ms.filter_precheck)
    check("默认 voice_analysis", ms.voice_analysis)
    check("默认 whisper_transcribe", ms.whisper_transcribe)
    check("默认 llm_compare", ms.llm_compare)
    check("默认 post_process", ms.post_process)
    check("默认 error_visualize", ms.error_visualize)

    # 单独关闭
    ms2 = ModuleSwitches(voice_analysis=False, llm_compare=False)
    check("关闭 voice", not ms2.voice_analysis)
    check("关闭 llm", not ms2.llm_compare)
    check("其他仍开启", ms2.whisper_transcribe and ms2.post_process)


# ==============================================================================
# 第 10 组：进度文件格式兼容性
# ==============================================================================
def test_progress_format():
    """验证 progress.json 读写的向前兼容性。"""
    from src.launcher import load_progress, update_student_progress, save_progress
    import src.launcher as lm

    tmpdir = tempfile.mkdtemp(prefix="verify_progress_")

    try:
        # 设置全局路径
        old_path = lm.progress_path
        old_data = lm.progress_data
        lm.progress_path = os.path.join(tmpdir, "progress.json")

        # 创建初始进度
        lm.progress_data = {"students": {}}
        update_student_progress("test-A", voice="done", text="done", accuracy=0.85)
        update_student_progress("test-B", voice="running")

        # 加载并验证
        data, done, rows = load_progress({"test-A": "/fake/a.mp3", "test-B": "/fake/b.mp3"})
        check("load progress data", "students" in data)
        check("done 含 test-A", "test-A" in done)
        check("done 不含 test-B", "test-B" not in done)
        check("rows 至少 1 条", len(rows) >= 1)

        # 测试 _build_summary_row
        row = lm._build_summary_row("test-A", {
            "voice": "done", "text": "done",
            "accuracy": 0.85,
            "语音综合分": 78.5,
        })
        check("summary row 含学生名", row.get("学生") == "test-A")
        check("summary row 含准确率", row.get("单词准确率") == 0.85)
        check("summary row 含总成绩", "总成绩" in row)
        # 总成绩 = 0.85 * 50 + 78.5 * 0.5 = 42.5 + 39.25 = 81.75
        check("summary row 总成绩计算",
              abs(row.get("总成绩", 0) - 81.75) < 0.01)

        # 恢复全局状态
        lm.progress_path = old_path
        lm.progress_data = old_data

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        lm.progress_path = old_path
        lm.progress_data = old_data


# ==============================================================================
# 第 11 组：OpenSMILE 列提取逻辑
# ==============================================================================
def test_opensmile_columns():
    """验证 extract_opensmile_columns 列定位逻辑。"""
    from src.utils import extract_opensmile_columns

    # 模拟 DataFrame
    class MockDF:
        def __init__(self):
            self.columns = type("MockIndex", (), {
                "tolist": lambda self: [
                    "F0final_sma", "voicingFinalUnclipped_sma",
                    "RMSenergy_sma", "spectralCentroid_sma",
                    "jitterLocal_sma", "shimmerLocal_sma",
                    "logHNR_sma", "otherColumn",
                ]
            })()

    mock_feat = MockDF()
    cols = extract_opensmile_columns(mock_feat)
    check_equal("F0 列", cols["f0_col"], "F0final_sma")
    check_equal("voicing 列", cols["voicing_col"], "voicingFinalUnclipped_sma")
    check_equal("energy 列", cols["energy_col"], "RMSenergy_sma")
    check_equal("centroid 列", cols["centroid_col"], "spectralCentroid_sma")
    check_equal("jitter 列", cols["jitter_col"], "jitterLocal_sma")
    check_equal("shimmer 列", cols["shimmer_col"], "shimmerLocal_sma")
    check_equal("hnr 列", cols["hnr_col"], "logHNR_sma")

    # 缺失列抛异常
    class MockBadDF:
        def __init__(self):
            self.columns = type("MockIndex", (), {
                "tolist": lambda self: ["only_one_column"]
            })()

    try:
        extract_opensmile_columns(MockBadDF())
        check("缺失列应抛异常", False)
    except ValueError:
        check("缺失列应抛异常", True)


# ==============================================================================
# 第 12 组：独立运行入口检查
# ==============================================================================
def test_standalone_entries():
    """验证各模块存在 if __name__ == '__main__' 入口。"""
    import ast

    modules = [
        ("src/voice_compare.py", "voice_compare"),
        ("src/text_llm.py", "text_llm"),
        ("src/audio_output.py", "audio_output"),
        ("src/filter_name.py", "filter_name"),
        ("src/error_visualizer.py", "error_visualizer"),
        ("src/launcher.py", "launcher"),
    ]

    for filename, label in modules:
        filepath = os.path.join(_project_root, filename)
        if not os.path.exists(filepath):
            check(f"{label} 文件存在", False)
            continue
        check(f"{label} 文件存在", True)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 检查是否有 if __name__ 入口
        has_main = 'if __name__ == "__main__"' in content
        check(f"{label} 有 __main__ 入口", has_main)


# ==============================================================================
# 第 13 组：临时文件清理
# ==============================================================================
def test_cleanup():
    """确保工作区无临时文件残留。"""
    result_dir = os.path.join(_project_root, "resource", "result")

    # 检查 project root 临时文件
    root_files = os.listdir(_project_root)
    temp_patterns = ["_norm", ".tmp", "_test_"]
    for f in root_files:
        for pat in temp_patterns:
            if pat in f:
                check(f"根目录无临时文件: {f}", False)
                break
        else:
            continue
        break
    else:
        check("根目录无临时文件", True)

    # 检查 __pycache__ 是否无残留
    pycache = os.path.join(_project_root, "__pycache__")
    if os.path.isdir(pycache):
        stale = []
        for pyc in os.listdir(pycache):
            if pyc.endswith(".pyc"):
                # 检查对应的 .py 是否存在
                py_name = pyc.replace(".cpython-313", "").replace(".pyc", ".py")
                # 在 src/ 中查找
                found = False
                for root, dirs, files in os.walk(os.path.join(_project_root, "src")):
                    if py_name in files:
                        found = True
                        break
                if not found and os.path.exists(os.path.join(_project_root, "run.py")):
                    # run.py 的特殊处理
                    if py_name != "run.py":
                        stale.append(pyc)
        check(f"__pycache__ 无残留 {len(stale)} 个", len(stale) == 0)
        if stale:
            for s in stale:
                print(f"    残留: {s}")


# ==============================================================================
# main
# ==============================================================================
def main():
    print("=" * 60)
    print("  语音仿读系统 — 重构综合验证")
    print(f"  时间: {datetime.now().isoformat()}")
    print(f"  项目路径: {_project_root}")
    print("=" * 60)

    # 依次运行所有测试分组
    run_section("第 1 组: 模块导入", test_imports)
    run_section("第 2 组: 常量验证", test_constants)
    run_section("第 3 组: 配置加载", test_config)
    run_section("第 4 组: 工具函数", test_utils)
    run_section("第 5 组: filter_name 模块", test_filter_name)
    run_section("第 6 组: audio_output 模块", test_audio_output)
    run_section("第 7 组: error_visualizer 模块", test_error_visualizer)
    run_section("第 8 组: CompletionTracker 逻辑", test_completion_tracker)
    run_section("第 9 组: 模块开关模拟", test_module_switches)
    run_section("第 10 组: 进度文件格式兼容性", test_progress_format)
    run_section("第 11 组: OpenSMILE 列提取逻辑", test_opensmile_columns)
    run_section("第 12 组: 独立运行入口检查", test_standalone_entries)
    run_section("第 13 组: 临时文件清理", test_cleanup)

    # 汇总
    total = _passed + _failed + _skipped
    print(f"\n{'=' * 60}")
    print(f"  验证完成")
    print(f"  通过: {_passed}  失败: {_failed}  跳过: {_skipped}  总计: {total}")
    print(f"{'=' * 60}")

    if _failed > 0:
        print("\n❌ 存在失败项，请检查上述输出。")
        sys.exit(1)
    else:
        print("\n✅ 所有验证通过！")
        sys.exit(0)


if __name__ == "__main__":
    main()
