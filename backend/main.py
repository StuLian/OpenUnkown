"""OpenUnknown 的 FastAPI 服务入口。

只负责组装应用：创建 FastAPI 实例、挂载静态资源、注册各业务路由。
HTTP 层统一收在 api/ 下：路由在 api/routers/，公共流式逻辑在 api/streaming.py，请求体模型在 api/schemas.py。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.config import APP_NAME
from backend.api.routers import auth, chat, files, mcp, sessions, settings, usage

app = FastAPI(title=APP_NAME)

# React 前端构建产物（frontend/dist）。dist 不入库，由 deploy_local.sh 在本地构建后
# 随部署包上传；本地开发时先执行 `cd frontend && npm run build`。
# 服务器无需安装 Node，FastAPI 直接托管构建出的静态资源。
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
# 预先创建 assets 目录：dist 未构建时 StaticFiles 首次请求返回 404 而非抛 500，
# 且构建完成后无需重启即可直接托管新产物。
(FRONTEND_DIST / "assets").mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

# 注册各业务领域路由
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(sessions.router)
app.include_router(mcp.router)
app.include_router(settings.router)
app.include_router(usage.router)


@app.get("/")
def index() -> Response:
    """返回 React 前端入口；未构建时给出明确提示。"""
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.exists():
        return PlainTextResponse(
            "前端尚未构建：请在 frontend/ 目录执行 `npm install && npm run build` 后重启服务。",
            status_code=503,
        )
    return FileResponse(index_file)
