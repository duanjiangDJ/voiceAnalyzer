"""
LLM 模型/模式自动对比基准测试
==============================
四轮测试：
  1. deepseek-v4-flash + 思考模式
  2. deepseek-v4-flash + 非思考模式
  3. deepseek-v4-pro   + 思考模式
  4. deepseek-v4-pro   + 非思考模式

每轮：运行完整 launcher.py → 记录耗时 + 汇总 → 保存结果。
"""
import csv
import glob
import os
import shutil
import subprocess
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
RESULT_DIR = os.path.join(BASE_DIR, "resource", "result")
PROGRESS_FILE = os.path.join(RESULT_DIR, "progress.json")
SUMMARY_FILE = os.path.join(RESULT_DIR, "summary.csv")
PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
BENCH_DIR = os.path.join(RESULT_DIR, "benchmark")
LAUNCHER_SCRIPT = os.path.join(BASE_DIR, "src", "launcher.py")

# ---- 测试矩阵 ----
TESTS = [
    {"model": "deepseek-v4-flash", "thinking": True,  "label": "Flash + 思考"},
    {"model": "deepseek-v4-flash", "thinking": False, "label": "Flash (无思考)"},
    {"model": "deepseek-v4-pro",   "thinking": True,  "label": "Pro + 思考"},
    {"model": "deepseek-v4-pro",   "thinking": False, "label": "Pro (无思考)"},
]


def run_launcher(model: str, thinking: bool, label: str, round_dir: str) -> dict:
    """运行一次完整 launcher，返回 {耗时, summary行列表, exit_code}"""

    # 彻底清理上一轮结果（进度文件 + 学生目录），确保每轮完全独立
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    if os.path.exists(SUMMARY_FILE):
        os.remove(SUMMARY_FILE)
    # 删除所有学生子目录和中间文件
    for item in os.listdir(RESULT_DIR):
        item_path = os.path.join(RESULT_DIR, item)
        if os.path.isdir(item_path) and item != "benchmark":
            shutil.rmtree(item_path)
        elif os.path.isfile(item_path) and item not in (".gitkeep",):
            os.remove(item_path)
    # 清理 imitation_audio 中残留的 _norm.wav
    for f in glob.glob(os.path.join(BASE_DIR, "resource", "imitation_audio", "*_norm*")):
        os.remove(f)

    env = os.environ.copy()
    env["LLM_MODEL"] = model
    env["LLM_THINKING"] = "1" if thinking else "0"
    env["PYTHONUNBUFFERED"] = "1"

    print(f"\n{'#' * 60}")
    print(f"▶ {label}")
    print(f"  模型={model}  思考={'开' if thinking else '关'}")
    print(f"{'#' * 60}")

    t0 = time.time()

    # 实时输出 + 同时捕获（写入日志文件）
    log_file = os.path.join(round_dir, "launcher_output.log")
    log_fh = open(log_file, "w", encoding="utf-8")
    stdout_buf: list[str] = []

    process = subprocess.Popen(
        [PYTHON, "-u", LAUNCHER_SCRIPT],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    for line in process.stdout:
        print(line, end="")      # 实时输出到控制台
        log_fh.write(line)       # 写入日志文件
        stdout_buf.append(line)  # 保留内存副本

    process.wait()
    log_fh.close()
    elapsed = time.time() - t0
    stdout_all = "".join(stdout_buf)

    # 复制结果文件
    if os.path.exists(SUMMARY_FILE):
        shutil.copy2(SUMMARY_FILE, os.path.join(round_dir, "summary.csv"))
    if os.path.exists(PROGRESS_FILE):
        shutil.copy2(PROGRESS_FILE, os.path.join(round_dir, "progress.json"))

    # 复制学生报告
    reports_dir = os.path.join(round_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    for item in os.listdir(RESULT_DIR):
        item_path = os.path.join(RESULT_DIR, item)
        if os.path.isdir(item_path) and item != "benchmark":
            dest = os.path.join(reports_dir, item)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(item_path, dest)

    return {
        "label": label,
        "model": model,
        "thinking": thinking,
        "elapsed": elapsed,
        "exit_code": process.returncode,
        "summary": _load_summary(),
        "log_file": log_file,
        "stdout": stdout_all,
    }


def _load_summary() -> list[dict]:
    if not os.path.exists(SUMMARY_FILE):
        return []
    rows = []
    with open(SUMMARY_FILE, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _parse_pct(s: str) -> float:
    """'85.23%' → 0.8523"""
    try:
        return float(s.rstrip("%")) / 100
    except (ValueError, AttributeError):
        return 0.0


def generate_report(results: list[dict], report_path: str) -> None:
    """生成汇总对比 Markdown 报告"""
    lines = []
    lines.append("# LLM 模型/模式基准测试报告")
    lines.append(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # ---- 总耗时对比 ----
    lines.append("## 1. 总耗时对比")
    lines.append("")
    lines.append("| 测试 | 模型 | 思考模式 | 总耗时 | 退出码 |")
    lines.append("|------|------|----------|--------|--------|")
    for r in results:
        think = "开" if r["thinking"] else "关"
        elapsed_str = f"{r['elapsed']:.0f}s ({r['elapsed']/60:.1f}min)"
        lines.append(
            f"| {r['label']} | {r['model']} | {think} | {elapsed_str} | {r['exit_code']} |"
        )
    lines.append("")

    # ---- 准确率对比 ----
    lines.append("## 2. 准确率对比")
    lines.append("")

    # 收集所有学生名
    all_names = set()
    name_accs: dict[str, dict[int, float]] = {}
    for idx, r in enumerate(results):
        for row in r["summary"]:
            name = row.get("学生", "")
            all_names.add(name)
            if name not in name_accs:
                name_accs[name] = {}
            name_accs[name][idx] = _parse_pct(row.get("单词准确率", "0%"))

    # 表头
    header = "| 学生 |"
    sep = "|------|"
    for r in results:
        header += f" {r['label']} |"
        sep += "------|"
    lines.append(header)
    lines.append(sep)

    for name in sorted(all_names):
        row = f"| {name} |"
        for idx in range(len(results)):
            acc = name_accs.get(name, {}).get(idx, 0)
            row += f" {acc*100:.2f}% |"
        lines.append(row)
    lines.append("")

    # 平均准确率
    avg_row = "| **平均** |"
    for idx, r in enumerate(results):
        accs = [name_accs.get(n, {}).get(idx, 0) for n in all_names]
        avg = sum(accs) / len(accs) if accs else 0
        avg_row += f" **{avg*100:.2f}%** |"
    lines.append(avg_row)
    lines.append("")

    # ---- 综合评分对比 ----
    lines.append("## 3. 综合评分对比")
    lines.append("")
    lines.append("| 测试 | 平均准确率 | 平均语音分 | 平均总成绩 |")
    lines.append("|------|-----------|-----------|-----------|")
    for r in results:
        rows = r["summary"]
        if not rows:
            lines.append(f"| {r['label']} | N/A | N/A | N/A |")
            continue
        avg_acc = sum(_parse_pct(row.get("单词准确率", "0%")) for row in rows) / len(rows)
        avg_voice = sum(float(row.get("语音综合分", 0)) for row in rows) / len(rows)
        avg_total = sum(float(row.get("总成绩", 0)) for row in rows) / len(rows)
        lines.append(
            f"| {r['label']} | {avg_acc*100:.2f}% | {avg_voice:.2f} | {avg_total:.2f} |"
        )
    lines.append("")

    # ---- 结论 ----
    lines.append("## 4. 结论")
    lines.append("")
    if len(results) >= 1:
        # 找最快
        fastest = min(results, key=lambda r: r["elapsed"])
        lines.append(f"- **最快**: {fastest['label']} ({fastest['elapsed']:.0f}s)")

        # 找最准
        best = max(
            results,
            key=lambda r: (
                sum(_parse_pct(row.get("单词准确率", "0%")) for row in r["summary"])
                / len(r["summary"])
                if r["summary"]
                else 0
            ),
        )
        if best["summary"]:
            avg = (
                sum(
                    _parse_pct(row.get("单词准确率", "0%"))
                    for row in best["summary"]
                )
                / len(best["summary"])
            )
            lines.append(f"- **最准**: {best['label']} (平均准确率 {avg*100:.2f}%)")

        # 性价比
        if fastest["label"] == best["label"]:
            lines.append(f"- ✅ **推荐**: {fastest['label']}（兼顾速度与准确率）")
        else:
            lines.append(f"- ⚖️ 速度优先选 {fastest['label']}，准确率优先选 {best['label']}")

    lines.append("")
    lines.append("---")
    lines.append("*详细报告见各轮次的 `reports/` 子目录*")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n" + "=" * 60)
    print("📊 汇总报告已保存:", report_path)
    # 同时打印到控制台
    print("\n".join(lines))


def main():
    print("LLM 基准测试 — 4 轮对比")
    print(f"Python: {PYTHON}\n")

    # 创建基准测试输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bench_run_dir = os.path.join(BENCH_DIR, timestamp)
    os.makedirs(bench_run_dir, exist_ok=True)

    results = []
    for test in TESTS:
        round_dir = os.path.join(bench_run_dir, test["label"].replace(" ", "_").replace("(", "").replace(")", ""))
        os.makedirs(round_dir, exist_ok=True)

        r = run_launcher(
            model=test["model"],
            thinking=test["thinking"],
            label=test["label"],
            round_dir=round_dir,
        )
        results.append(r)

        status = "✅" if r["exit_code"] == 0 else f"❌ (exit={r['exit_code']})"
        print(f"\n  {status} {test['label']}: {r['elapsed']:.0f}s ({r['elapsed']/60:.1f}min)")

    # 生成汇总报告
    report_path = os.path.join(bench_run_dir, "benchmark_report.md")
    generate_report(results, report_path)

    # 复制最终报告到项目根
    shutil.copy2(report_path, os.path.join(BASE_DIR, "benchmark_report.md"))

    print(f"\n全部完成。结果保存在: {bench_run_dir}")
    print(f"汇总报告: {report_path}")


if __name__ == "__main__":
    main()
