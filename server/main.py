"""
main.py — FastAPI 应用入口
=========================
创建本地 Web UI 后端应用，注册 REST API、SSE 事件流并托管前端静态资源。

依赖:
    - pathlib（标准库）
    - fastapi（第三方）
    - services.*（项目内部 UI 服务层）
"""

import time
from pathlib import Path

from fastapi import Request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from server.api.v1 import classes, config, exports, files, health, logs, results, tasks, archived
from server.events import sse
from services.app_context import get_app_context
from services.log_service import get_log_service


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例。

    返回:
        配置完成的 FastAPI 应用。
    """
    app = FastAPI(title="语音仿读质量评估系统 UI", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        time_start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            get_log_service().append(
                "api", "ERROR",
                f"{request.method} {request.url.path} 500 (unhandled exception)",
                {"path": request.url.path, "method": request.method, "status_code": 500},
            )
            raise
        if request.url.path.startswith("/api") or response.status_code >= 500:
            get_log_service().append(
                "api",
                "INFO" if response.status_code < 400 else "ERROR",
                f"{request.method} {request.url.path} {response.status_code}",
                {
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "time_ms": round((time.time() - time_start) * 1000, 2),
                },
            )
        return response

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(classes.router, prefix="/api/v1")
    app.include_router(logs.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(config.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(results.router, prefix="/api/v1")
    app.include_router(exports.router, prefix="/api/v1")
    app.include_router(archived.router, prefix="/api/v1")
    app.include_router(sse.router)

    context = get_app_context()
    static_dir = Path(context.base_dir) / "ui" / "dist"
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/{path:path}", include_in_schema=False)
        def spa_fallback(path: str) -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app