"""基于 LangGraph 的问答 agent 图。

当前只做最基础的多轮问答，后续可以在此扩展工具调用、检索等能力。
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import tools_condition
from langgraph.types import interrupt
from typing_extensions import TypedDict

from backend.agent.context import (
    assemble_model_messages,
    extract_text_content,
    log_llm_input,
)
from backend.agent.llm import get_llm
from backend.agent.mcp import get_enabled_mcp_tools
from backend.agent.prompts import IDENTITY_PROMPT, LARK_SECTION, build_system_prompt
from backend.agent.router import route_intents
from backend.agent.tools import TOOLS as BUILTIN_TOOLS
from backend.agent.tools.lark_cli import classify_risk, ensure_yes, load_skill_descriptions
from backend.config import (
    APP_NAME,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_PLATFORM,
    get_platform,
    mode_enables_thinking,
)

logger = logging.getLogger(__name__)

# checkpoint 数据库与 store 共用同一个 db 文件(项目根 data/openunknown.db)
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "openunknown.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 单轮对话最多允许的工具执行次数，超过后强制模型停止调用工具直接作答，
# 避免工具反复失败(如搜索被限流)时模型无限重试、触发 LangGraph 的 recursion limit。
MAX_TOOL_CALLS = 8


def _tool_calls_this_turn(messages: list) -> int:
    """统计本轮(最近一条 human 消息之后)已执行的工具调用次数。"""
    count = 0
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "human":
            break
        if getattr(msg, "type", None) == "tool":
            count += 1
    return count

# 工具意图预筛已抽到 backend/agent/router.py：关键词快速通道 + embedding 语义召回兜底。
# 这里只按 route_intents 的结果决定本轮绑定哪些工具，避免闲聊也带上全部工具 schema。


def _latest_user_text(messages: list) -> str:
    """取最近一条用户消息文本，作为工具预筛的意图依据。"""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "human":
            return extract_text_content(getattr(msg, "content", ""))
    return ""


def _prev_user_text(messages: list) -> str:
    """取倒数第二条用户消息文本，用于短跟随消息继承上一轮意图。"""
    seen = 0
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "human":
            seen += 1
            if seen == 2:
                return extract_text_content(getattr(msg, "content", ""))
    return ""


def _mcp_server_name(desc: str) -> str:
    """从 MCP 工具描述 '[MCP: 服务名] ...' 里解析服务名。"""
    desc = desc.lower()
    if desc.startswith("[mcp:"):
        end = desc.find("]")
        if end != -1:
            return desc[5:end].strip()
    return ""


def _mcp_tool_hit(tool, text: str) -> bool:
    """未归类的 MCP 工具：用户点名服务名或工具名 token 命中才绑定。"""
    server = _mcp_server_name(getattr(tool, "description", "") or "")
    if server and server in text:
        return True
    return any(len(tok) >= 3 and tok in text for tok in tool.name.lower().split("_"))


def _select_tools(tools: list, text: str, want: dict) -> list:
    """按意图预筛本轮要绑定的工具：闲聊返回空列表，命中才绑对应工具。"""
    selected = []
    for t in tools:
        name = t.name
        if name == "get_weather":
            if want["weather"]:
                selected.append(t)
        elif name == "lark_cli":
            if want["feishu"]:
                selected.append(t)
        elif name in ("browser_fetch", "browser_search"):
            if want["browse"]:
                selected.append(t)
        elif name.startswith("maps_"):
            if want["map"] or (want["weather"] and "weather" in name):
                selected.append(t)
        elif name == "search_hotels":
            if want["hotel"]:
                selected.append(t)
        elif _mcp_tool_hit(t, text):
            selected.append(t)
    return selected


# 飞书 domain 列表缓存（纯数据行，仅加载一次）
_lark_domain_list: str | None = None


async def _get_system_prompt(include_lark: bool) -> str:
    """用模板组装 system prompt；仅命中飞书意图时追加 domain 短目录。"""
    global _lark_domain_list
    base = build_system_prompt(APP_NAME)
    if not include_lark:
        return base
    if _lark_domain_list is None:
        _lark_domain_list = await load_skill_descriptions()
    if not _lark_domain_list:
        return base
    return base + "\n" + LARK_SECTION.format(domain_list=_lark_domain_list)


async def _get_all_tools(user_id: str):
    """获取指定用户所有生效的工具列表（内置工具 + 其启用的 MCP 工具）。"""
    mcp_tools = await get_enabled_mcp_tools(user_id)
    return [*BUILTIN_TOOLS, *mcp_tools]


async def _chat_node(state: MessagesState, config: RunnableConfig) -> dict:
    """核心问答节点：动态绑定当前可用工具，把历史消息交给所选模型生成回复。

    模型由上层通过 config.configurable.model 指定，使用异步调用便于客户端断开时中断请求。
    本轮工具调用次数达到上限后不再绑定工具，强制模型直接作答，保证图一定能收敛。
    """
    cfg = config.get("configurable") or {}
    collector = cfg.get("trace_collector")
    model_name = cfg.get("model") or DEFAULT_MODEL
    mode = cfg.get("mode") or DEFAULT_MODE
    platform = cfg.get("platform") or DEFAULT_PLATFORM
    api_key = cfg.get("api_key") or ""
    user_id = cfg.get("user_id") or ""
    session_id = cfg.get("session_id") or ""
    enable_thinking = mode_enables_thinking(mode)
    force_answer = _tool_calls_this_turn(state["messages"]) >= MAX_TOOL_CALLS

    # 按本轮用户意图预筛工具：关键词命中零延迟直绑，未命中走 embedding 语义召回兜底
    user_text = _latest_user_text(state["messages"]).lower()
    want = await route_intents(
        user_text,
        api_key=api_key,
        prev_user_text=_prev_user_text(state["messages"]),
    )
    all_tools = await _get_all_tools(user_id)
    bound_tools = [] if force_answer else _select_tools(all_tools, user_text, want)

    llm = get_llm(
        model_name,
        enable_thinking=enable_thinking,
        api_key=api_key,
        base_url=get_platform(platform)["base_url"],
    )
    if bound_tools:
        llm = llm.bind_tools(bound_tools)
    system_prompt = await _get_system_prompt(include_lark=want["feishu"])
    # 身份指令合并进首条系统提示（放历史之前），避免成为最后一条消息干扰模型作答
    # （此前放在历史末尾，视觉模型会把它当成当前任务，回答成「我是什么模型」）。
    identity_text = IDENTITY_PROMPT.format(model_name=model_name)
    # 记忆注入（滚动摘要 + 长记忆召回）与历史压缩统一在 context 层完成。
    # 记忆是独立的 kind=memory 消息，与基础 system 分开；DashScope 兼容接口实测
    # 支持多条/任意位置的 system（全部在册模型 200 OK），故直接原样发送，
    # trace 记录的就是真实报文、不做任何合并（保真）。
    messages, mem_info = await assemble_model_messages(
        state_messages=list(state["messages"]),
        system_prompt=system_prompt,
        identity_text=identity_text,
        user_id=user_id,
        session_id=session_id,
        query=_latest_user_text(state["messages"]),
        api_key=api_key,
        base_url=get_platform(platform)["base_url"],
        force_answer=force_answer,
    )
    if collector is not None:
        if mem_info.get("memory_injected"):
            collector.add_flag("memory_injected")
        collector.record_llm_input(messages)
    logger.info(
        "[LLM 输入] 本轮绑定工具 %d/%d；模式=%s(思考=%s)；注入记忆=%s 触发摘要=%s",
        len(bound_tools),
        len(all_tools),
        mode,
        enable_thinking,
        mem_info.get("memory_injected"),
        mem_info.get("summarized"),
    )
    log_llm_input(model_name, messages, [t.name for t in bound_tools])
    response = await llm.ainvoke(messages)
    return {"messages": [response]}


async def _tools_node(state: MessagesState, config: RunnableConfig) -> dict:
    """动态工具执行节点：根据最新消息中的 tool_calls 找到对应的工具执行并返回 ToolMessage。

    把 RunnableConfig 透传给工具，使需要调用模型服务的工具（如酒店检索）能取到
    当前用户的 ApiKey 与平台配置。

    飞书安全闸门：凡是会被 lark_cli 判定为 write/high-risk-write 的命令，在执行
    **任何**工具之前先 interrupt() 暂停图，等前端用户确认后才放行。interrupt 放在
    所有执行之前，是因为 resume 时节点会从头部重跑——若先执行了读操作，会重复执行。
    """
    last_msg = state["messages"][-1]
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {"messages": []}

    cfg = config.get("configurable") or {}
    collector = cfg.get("trace_collector")
    user_id = cfg.get("user_id") or ""
    all_tools = await _get_all_tools(user_id)
    tool_map = {t.name: t for t in all_tools}
    tool_calls = list(last_msg.tool_calls)

    # 先扫描是否存在飞书写操作；找到首个写操作即中断等确认。
    # resume 后 interrupt() 在同一位置返回前端传来的决策值（{"approved": bool}）。
    decision = None
    for tc in tool_calls:
        if tc.get("name") != "lark_cli":
            continue
        command = (tc.get("args") or {}).get("command", "")
        risk = await classify_risk(command)
        if risk in ("write", "high-risk-write"):
            decision = interrupt({
                "type": "lark_write_confirmation",
                "tool_call_id": tc.get("id"),
                "command": command,
                "risk": risk,
            })
            break

    approved = isinstance(decision, dict) and decision.get("approved") is True

    results = []
    for tc in tool_calls:
        tool_name = tc.get("name")
        tool_args = tc.get("args") or {}
        call_id = tc.get("id")

        logger.info("[工具] 调用 %s, 参数: %s", tool_name, tool_args)
        tool = tool_map.get(tool_name)
        if not tool:
            output = f"Error: Tool '{tool_name}' not found or not enabled."
        elif tool_name == "lark_cli":
            command = tool_args.get("command", "")
            risk = await classify_risk(command)
            if risk in ("write", "high-risk-write") and not approved:
                output = (
                    "用户未确认该飞书写操作，未执行任何变更。"
                    "请向用户说明该操作已取消，并询问是否需要调整后重试。"
                )
            else:
                invoke_args = dict(tool_args)
                # high-risk-write 需 --yes 才会真正执行：用户确认即授权，这里补上
                if risk == "high-risk-write":
                    invoke_args["command"] = ensure_yes(command)
                try:
                    output = await tool.ainvoke(invoke_args, config=config)
                except Exception as e:
                    output = f"Error executing tool '{tool_name}': {e}"
        else:
            try:
                output = await tool.ainvoke(tool_args, config=config)
            except Exception as e:
                output = f"Error executing tool '{tool_name}': {e}"
        preview = str(output)[:300]
        logger.info("[工具] %s 返回(前300字): %s", tool_name, preview)

        if collector is not None:
            collector.record_tool_call(tc)
            collector.record_tool_output(call_id, tool_name, str(output))

        results.append(ToolMessage(content=str(output), tool_call_id=call_id, name=tool_name))

    return {"messages": results}


class GraphConfig(TypedDict):
    """图运行时配置：thread_id 由 checkpointer 使用；其余为本轮参数。"""

    thread_id: str
    model: str
    mode: str
    platform: str
    api_key: str
    user_id: str


# 异步 checkpointer 单例(需异步 setup，故用模块级缓存而非 lru_cache)
_checkpointer: AsyncSqliteSaver | None = None
_graph = None


async def get_graph():
    """构建并编译问答图，使用异步 sqlite checkpointer 支持多轮会话持久化。"""
    global _checkpointer, _graph
    if _graph is None:
        import aiosqlite

        conn = await aiosqlite.connect(str(DB_PATH))
        await conn.execute("PRAGMA journal_mode=WAL")
        # langgraph-checkpoint-sqlite 2.0.11 的 setup 会调 conn.is_alive()，
        # 而 aiosqlite.Connection 没有此方法，这里补一个恒真的实现以绕过该分支。
        if not hasattr(conn, "is_alive"):
            conn.is_alive = lambda: True
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()

        builder = StateGraph(MessagesState, config_schema=GraphConfig)
        builder.add_node("chat", _chat_node)
        builder.add_node("tools", _tools_node)
        builder.add_edge(START, "chat")
        builder.add_conditional_edges("chat", tools_condition)
        builder.add_edge("tools", "chat")
        _graph = builder.compile(checkpointer=_checkpointer)
    return _graph
