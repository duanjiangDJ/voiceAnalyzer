"""
build_exe.py — PyInstaller 打包脚本
==============================
将语音仿读评估系统打包为可独立分发的 Windows 文件夹。
重型依赖（PyTorch, Whisper, OpenSMILE）需用户预装 Python 环境。

用法:
    python build_exe.py              # 构建（生产模式）
    python build_exe.py --dev        # 开发模式（不含模型文件，更快）

输出: dist/voice_analyse/
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist" / "voice_analyse"


def clean_dist() -> None:
    """清理旧构建。"""
    for d in ["dist", "build"]:
        p = PROJECT_ROOT / d
        if p.exists():
            shutil.rmtree(p)
    for f in PROJECT_ROOT.glob("*.spec"):
        f.unlink()


def build_frontend() -> None:
    """构建 Vue 前端（如未构建）。"""
    dist = PROJECT_ROOT / "ui" / "dist" / "index.html"
    if dist.exists():
        print("[build] 前端已构建，跳过")
        return
    print("[build] 构建 Vue 前端 ...")
    subprocess.run(["npm", "run", "build"], cwd=PROJECT_ROOT / "ui", check=True)


def run_pyinstaller(dev_mode: bool = False) -> None:
    """调用 PyInstaller。"""
    # 数据文件映射
    datas = [
        ("resource", "resource"),
        ("ui/dist", "ui/dist"),
        ("stopwords.txt", "."),
    ]
    # 生产模式额外包含模型文件
    if not dev_mode:
        if (PROJECT_ROOT / "models").exists():
            datas.append(("models", "models"))

    hidden_imports = [
        "whisper",
        "matplotlib.backends.backend_agg",
        "multiprocessing",
        "sklearn.utils._weight_vector",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", "voice_analyse",
        "--clean",
        "--noconfirm",
    ]
    for src, dst in datas:
        cmd += ["--add-data", f"{src}{os.pathsep}{dst}"]
    for mod in hidden_imports:
        cmd += ["--hidden-import", mod]
    # 收集重型包的完整依赖
    for pkg in ["matplotlib", "wordcloud", "pandas", "numpy", "fastapi", "uvicorn"]:
        cmd += ["--collect-all", pkg]
    cmd.append(str(PROJECT_ROOT / "run_ui.py"))

    print(f"[build] PyInstaller: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def copy_extras(dev_mode: bool = False) -> None:
    """复制额外文件到输出目录。"""
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 复制启动说明
    readme_text = """# 语音仿读评估系统 - 便携版

## 启动
双击 `voice_analyse.exe` 或命令行运行 `voice_analyse.exe`。

## 首次使用
1. 编辑 `resource/config.yaml` 和 `.env` 配置 API 密钥
2. 将标准音频放入 `resource/units/{单元名}/standard_audio/`
3. 将仿读音频放入 `resource/classes/{班级名}/{单元名}/imitation_audio/`
4. 浏览器打开 http://127.0.0.1:8000

## 依赖
本程序需要系统已安装:
- Python 3.10+ 环境（含 PyTorch、Whisper、OpenSMILE）
"""
    (DIST_DIR / "使用说明.txt").write_text(readme_text, encoding="utf-8")

    # 复制文档
    doc_dest = DIST_DIR / "doc"
    doc_dest.mkdir(exist_ok=True)
    for f in (PROJECT_ROOT / "doc").glob("*.md"):
        shutil.copy2(f, doc_dest / f.name)

    if not dev_mode and (PROJECT_ROOT / "models").exists():
        shutil.copytree(PROJECT_ROOT / "models", DIST_DIR / "models", dirs_exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="打包脚本")
    parser.add_argument("--dev", action="store_true", help="开发模式（不含模型文件）")
    args = parser.parse_args()

    print("=" * 60)
    print("语音仿读评估系统 — PyInstaller 打包")
    print(f"模式: {'开发' if args.dev else '生产'}")
    print("=" * 60)

    clean_dist()
    build_frontend()
    run_pyinstaller(args.dev)
    copy_extras(args.dev)

    print(f"\n✅ 打包完成！输出目录: {DIST_DIR}")
    print(f"   可分发文件夹大小约 {_dir_size(DIST_DIR):.0f} MB")


def _dir_size(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)


if __name__ == "__main__":
    main()
