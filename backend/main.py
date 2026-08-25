"""OpenUnknown 的 FastAPI 服务入口。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from backend import store
from backend.agent import mcp
from backend.agent.graph import get_graph
from backend.config import (
    APP_NAME,
    AVAILABLE_MODELS,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    MODES,
    is_valid_mode,
    is_valid_model,
    mode_enables_thinking,
)

app = FastAPI(title=APP_NAME)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


class ChatRequest(BaseModel):
    """聊天请求体。"""

    message: str
    session_id: str
    model: str | None = None
    mode: str | None = None


class McpServerSaveRequest(BaseModel):
    """MCP Server 保存请求体。"""

    id: str | None = None
    name: str
    server_type: str = "stdio"
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    enabled: bool = True


class McpToggleRequest(BaseModel):
    """MCP Server 启停请求体。"""

    enabled: bool


class McpImportRequest(BaseModel):
    """MCP JSON 批量导入请求体。"""

    config: dict


@app.get("/")
def index() -> FileResponse:
    """返回前端聊天页面。"""
    return FileResponse(FRONTEND_DIR / "index.html")


def _sse(payload: dict) -> str:
    """把数据打包成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _msg_to_dict(m) -> dict | None:
    """把 LangChain 消息对象转成前端可用的 {role, content}。

    工具调用相关的中间消息不展示：tool 消息、以及仅包含 tool_calls 没有正文的 assistant 消息。
    """
    if m.type in ("system", "tool"):
        return None
    content = m.content if isinstance(m.content, str) else ""
    if m.type == "ai" and getattr(m, "tool_calls", None) and not content.strip():
        return None
    role = {"human": "user", "ai": "assistant"}.get(m.type, m.type)
    if role not in ("user", "assistant") or not content:
        return None
    return {"role": role, "content": content}


async def _stream_answer(message: str, session_id: str, model: str, mode: str, request: Request):
    """以 SSE 方式逐 token 返回所选模型/模式的回答。

    客户端断开(点击停止)时立即中断底层生成，结束时回传 token 用量。
    首条消息自动创建会话元数据，标题取首条消息。
    思考模式下额外推送 reasoning_content(thinking 事件)，供前端展示思考过程。
    """
    # 首条消息创建会话(已存在则忽略)，并更新时间
    store.create_session(session_id, message)
    store.touch_session(session_id)

    graph = await get_graph()
    config = {"configurable": {"thread_id": session_id, "model": model, "mode": mode}}
    inputs = {"messages": [HumanMessage(content=message)]}
    usage: dict | None = None

    yield _sse({"model": model, "mode": mode})

    try:
        async for chunk, meta in graph.astream(
            inputs, config=config, stream_mode="messages"
        ):
            # 客户端已断开则停止生成，async 生成器关闭会取消底层请求
            if await request.is_disconnected():
                break

            node = meta.get("langgraph_node")

            # tools 节点：推送工具调用详情给前端做透明化提示
            if node == "tools":
                # ToolMessage：工具执行完毕，推送结果摘要
                if chunk.type == "tool":
                    yield _sse({
                        "tool_result": {
                            "id": chunk.tool_call_id,
                            "tool": chunk.name,
                            "output": chunk.content[:300] if isinstance(chunk.content, str) else str(chunk.content)[:300],
                        }
                    })
                continue

            if node != "chat":
                continue

            # chat 节点：在 AI 开始生成正文之前，先推送本轮的 tool_calls 信息
            # 流式下同一个 tool_call 会分多个 chunk 到达，仅在 id 存在时推送一次
            if getattr(chunk, "tool_calls", None):
                for tc in chunk.tool_calls:
                    tc_id = tc.get("id")
                    if not tc_id:
                        continue
                    yield _sse({
                        "tool_call": {
                            "id": tc_id,
                            "tool": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                    })

            # 累积 token 用量(通常在最后一个 chunk 上)
            if getattr(chunk, "usage_metadata", None):
                usage = chunk.usage_metadata
            # 仅思考模式推送推理过程(reasoning_content)；快速模式保持直接回答，不展示思考
            if mode_enables_thinking(mode):
                reasoning = (
                    chunk.additional_kwargs.get("reasoning_content")
                    if getattr(chunk, "additional_kwargs", None)
                    else None
                )
                if isinstance(reasoning, str) and reasoning:
                    yield _sse({"thinking": reasoning})
            # 工具调用阶段 content 可能是空串或非字符串，只把最终自然语言增量推给前端
            text = chunk.content
            if isinstance(text, str) and text:
                yield _sse({"delta": text})
    except Exception as exc:  # noqa: BLE001
        yield _sse({"error": str(exc)})

    if usage:
        yield _sse({"usage": usage})
    yield "data: [DONE]\n\n"


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """流式问答接口。"""
    # 校验模型，非法或缺省时用默认模型（前端选择器只提供合法值，此处兜住异常入参）
    model = req.model if req.model and is_valid_model(req.model) else DEFAULT_MODEL
    # 校验模式，非法或缺省时用默认模式
    mode = req.mode if req.mode and is_valid_mode(req.mode) else DEFAULT_MODE
    return StreamingResponse(
        _stream_answer(req.message, req.session_id, model, mode, request),
        media_type="text/event-stream",
    )


@app.get("/api/models")
def list_models() -> dict:
    """返回可选模型列表与默认模型。"""
    return {"models": AVAILABLE_MODELS, "default": DEFAULT_MODEL}


@app.get("/api/modes")
def list_modes() -> dict:
    """返回可选回答模式列表与默认模式。"""
    return {"modes": MODES, "default": DEFAULT_MODE}


@app.get("/api/sessions")
def list_sessions() -> dict:
    """返回所有历史会话列表，按最近更新倒序。"""
    return {"sessions": store.list_sessions()}


@app.post("/api/sessions")
def create_session() -> dict:
    """新建一个空会话，返回其 id(前端也可本地生成，这里提供统一入口)。"""
    session_id = "sess-" + uuid.uuid4().hex
    store.create_session(session_id, "新对话")
    return {"id": session_id}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    """删除指定会话及其全部 checkpoint 数据。"""
    store.delete_session(session_id)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str) -> dict:
    """从 checkpoint 恢复指定会话的历史消息。"""
    graph = await get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph.aget_state(config)
    messages = state.values.get("messages", []) if state and state.values else []
    return {"messages": [d for m in messages if (d := _msg_to_dict(m))]}


# ===== MCP Server 管理 API =====

@app.get("/api/mcp/servers")
def get_mcp_servers() -> dict:
    """获取所有 MCP Server 配置。"""
    return {"servers": store.list_mcp_servers()}


@app.post("/api/mcp/servers")
def save_mcp_server(req: McpServerSaveRequest) -> dict:
    """保存或更新单个 MCP Server 配置。"""
    res = store.save_mcp_server(req.model_dump())
    # 连接参数可能已变，让下一轮对话重新拉工具列表
    mcp.invalidate_mcp_cache(res["id"] if res else None)
    return {"server": res}


@app.delete("/api/mcp/servers/{server_id}")
def delete_mcp_server(server_id: str) -> dict:
    """删除指定 MCP Server 配置。"""
    ok = store.delete_mcp_server(server_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found")
    mcp.invalidate_mcp_cache(server_id)
    return {"ok": True}


@app.patch("/api/mcp/servers/{server_id}/toggle")
def toggle_mcp_server(server_id: str, req: McpToggleRequest) -> dict:
    """切换指定 MCP Server 启用状态。"""
    res = store.toggle_mcp_server(server_id, req.enabled)
    if not res:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"server": res}


@app.post("/api/mcp/test")
async def test_mcp_connection(req: McpServerSaveRequest) -> dict:
    """测试连接 MCP Server 并获取它所提供的 Tools 列表。"""
    try:
        tools = await mcp.test_mcp_server(req.model_dump())
        return {"ok": True, "tools": tools}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "tools": []}


@app.post("/api/mcp/import")
def import_mcp_json(req: McpImportRequest) -> dict:
    """从标准 JSON 批量导入 MCP Servers。"""
    try:
        imported = store.import_mcp_servers_from_json(req.config)
        mcp.invalidate_mcp_cache()
        return {"ok": True, "imported_count": len(imported), "servers": imported}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}")
