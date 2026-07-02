"""
run.py — 语音仿读质量评估系统总入口
=====================================
从项目根目录一键启动完整流水线。

用法:
    python run.py

等价于:
    python src/launcher.py
"""

import sys
import os

# 确保项目根目录在 path 中
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.launcher import main

if __name__ == "__main__":
    main()
