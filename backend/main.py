"""OpenUnknown 的 FastAPI 服务入口。

只负责组装应用：创建 FastAPI 实例、挂载静态资源、注册各业务路由。
HTTP 层统一收在 api/ 下：路由在 api/routers/，公共流式逻辑在 api/streaming.py，请求体模型在 api/schemas.py。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import APP_NAME
from backend.api.routers import auth, chat, mcp, sessions, settings

app = FastAPI(title=APP_NAME)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

# 注册各业务领域路由
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(mcp.router)
app.include_router(settings.router)


@app.get("/")
def index() -> FileResponse:
    """返回前端聊天页面。"""
    return FileResponse(FRONTEND_DIR / "index.html")
