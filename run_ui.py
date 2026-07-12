"""
run_ui.py — 本地 Web UI 启动入口
===============================
一键启动语音仿读质量评估系统的浏览器图形界面。

功能：
  1. 检查并启动 FastAPI 本地服务
  2. 托管 ui/dist 下的前端静态资源
  3. 自动打开默认浏览器访问 UI

依赖:
    - sys, os, threading, time, webbrowser（标准库）
    - uvicorn（第三方）
    - server.main（项目内部模块）
"""

import os
import sys
import threading
import time
import webbrowser

import uvicorn


_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _open_browser(url: str) -> None:
    """稍等服务启动后打开默认浏览器。"""
    time.sleep(2)
    webbrowser.open(url)


def main() -> None:
    """
    启动本地 Web UI。

    返回:
        None。该函数会阻塞当前进程直到服务退出。
    """
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"
    print(f"[UI] 正在启动语音仿读质量评估系统 UI: {url}")
    threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    # 注意：本地 Web UI 依赖全局单例（PipelineService/LogService），
    # 仅支持单 worker 模式。多 worker 部署需额外引入进程间共享机制。
    uvicorn.run("server.main:create_app", factory=True, host=host, port=port, workers=1, reload=False)


if __name__ == "__main__":
    main()