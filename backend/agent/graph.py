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
from typing_extensions import TypedDict

from backend.agent.llm import get_llm
from backend.agent.mcp import get_enabled_mcp_tools
from backend.agent.prompts import IDENTITY_PROMPT, LARK_SECTION, SYSTEM_PROMPT
from backend.agent.tools import TOOLS as BUILTIN_TOOLS
from backend.agent.tools.lark_cli import load_skill_descriptions
from backend.config import APP_NAME, DEFAULT_MODE, DEFAULT_MODEL, mode_enables_thinking

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

# 关键词预筛：按用户当轮意图决定这一轮绑定哪些工具，避免闲聊也带上全部工具 schema。
# 工具 schema 是每轮固定 token 大头（高德一家就 12 个），命中才绑，能显著降低底噪。
_WEATHER_KWS = (
    "天气", "气温", "温度", "下雨", "下雪", "降雨", "降温", "气候",
    "冷不冷", "热不热", "多少度", "weather",
)
_MAP_KWS = (
    "地图", "路线", "路况", "导航", "规划", "怎么走", "怎么去", "附近", "周边",
    "位置", "坐标", "经纬", "距离", "多远", "骑行", "步行", "驾车", "开车",
    "公交", "地铁", "打车", "高德", "地址", "在哪", "poi",
)
_FEISHU_KWS = (
    "飞书", "lark", "文档", "docx", "wiki", "多维表格", "电子表格", "表格",
    "sheet", "日历", "日程", "会议", "待办", "任务", "邮件", "邮箱",
    "云盘", "云空间", "知识库", "妙记", "审批", "通讯录", "考勤",
    "幻灯片", "画板", "okr", "feishu.cn", "larksuite",
)
_BROWSE_KWS = (
    "网页", "网站", "网址", "链接", "打开网页", "浏览", "抓取", "爬取", "访问网页",
    "上网", "在线", "互联网", "搜索", "检索", "搜一下", "搜索引擎", "热搜",
    "新闻", "资讯", "最新消息", "web", "url", "http", "browse", "search", "fetch",
    # 股票/财经类：无专门行情工具，统一路由到 browser_search 联网检索
    "股票", "股价", "行情", "大盘", "上证", "深证", "涨跌", "涨幅", "跌幅",
    "市值", "财报", "美股", "港股", "a股", "收盘", "开盘", "证券",
)


def _hit(text: str, kws: tuple[str, ...]) -> bool:
    """判断文本是否命中关键词组。"""
    return any(k in text for k in kws)


def _latest_user_text(messages: list) -> str:
    """取最近一条用户消息文本，作为工具预筛的意图依据。"""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", "")
            return content if isinstance(content, str) else str(content)
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
        elif _mcp_tool_hit(t, text):
            selected.append(t)
    return selected


# 发给模型时：尾部消息保持原文（覆盖当前工具轮），更早的超长工具结果截断。
# 不改 checkpoint，只压缩本轮 LLM 输入。
_KEEP_TAIL = 16
_OLD_TOOL_CHARS = 240


def _compact_history(messages: list) -> list:
    """压缩历史中的旧工具原文，避免长对话每轮把全部工具返回再送给模型。"""
    if len(messages) <= _KEEP_TAIL:
        return list(messages)

    head, tail = messages[:-_KEEP_TAIL], messages[-_KEEP_TAIL:]
    compacted = []
    for msg in head:
        if getattr(msg, "type", None) != "tool":
            compacted.append(msg)
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if len(content) <= _OLD_TOOL_CHARS:
            compacted.append(msg)
            continue
        compacted.append(ToolMessage(
            content=content[:_OLD_TOOL_CHARS] + f"\n...(已截断，原文 {len(content)} 字)",
            tool_call_id=msg.tool_call_id,
            name=getattr(msg, "name", None),
        ))
    return compacted + list(tail)


def _messages_chars(messages: list) -> int:
    """粗算消息文本总字数，便于日志对比压缩效果。"""
    total = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        total += len(content) if isinstance(content, str) else len(str(content))
    return total


# 飞书 domain 列表缓存（纯数据行，仅加载一次）
_lark_domain_list: str | None = None


async def _get_system_prompt(include_lark: bool) -> str:
    """用模板组装 system prompt；仅命中飞书意图时追加 domain 短目录。"""
    global _lark_domain_list
    base = SYSTEM_PROMPT.format(app_name=APP_NAME)
    if not include_lark:
        return base
    if _lark_domain_list is None:
        _lark_domain_list = await load_skill_descriptions()
    if not _lark_domain_list:
        return base
    return base + "\n" + LARK_SECTION.format(domain_list=_lark_domain_list)


def _log_llm_input(model_name: str, messages: list, tool_names: list[str]) -> None:
    """把本轮发给大模型的提示词打印到服务日志，方便核对。"""
    lines = [
        "",
        "=" * 72,
        f"[LLM 输入] 模型={model_name}  消息数={len(messages)}  约 { _messages_chars(messages) } 字  绑定工具={tool_names}",
        "=" * 72,
    ]
    for i, msg in enumerate(messages):
        role = getattr(msg, "type", msg.__class__.__name__)
        name = getattr(msg, "name", None) or ""
        content = msg.content if isinstance(getattr(msg, "content", None), str) else str(getattr(msg, "content", ""))
        header = f"[{i}] {role}" + (f" ({name})" if name else "")
        lines.append(header)
        lines.append(content if content else "(空)")
        if getattr(msg, "tool_calls", None):
            lines.append(f"  tool_calls: {msg.tool_calls}")
        lines.append("-" * 40)
    lines.append("=" * 72)
    text = "\n".join(lines)
    logger.info(text)
    print(text, flush=True)


async def _get_all_tools():
    """获取所有生效的工具列表（内置工具 + 当前启用的 MCP 工具）。"""
    mcp_tools = await get_enabled_mcp_tools()
    return [*BUILTIN_TOOLS, *mcp_tools]


async def _chat_node(state: MessagesState, config: RunnableConfig) -> dict:
    """核心问答节点：动态绑定当前可用工具，把历史消息交给所选模型生成回复。

    模型由上层通过 config.configurable.model 指定，使用异步调用便于客户端断开时中断请求。
    本轮工具调用次数达到上限后不再绑定工具，强制模型直接作答，保证图一定能收敛。
    """
    model_name = (config.get("configurable") or {}).get("model") or DEFAULT_MODEL
    mode = (config.get("configurable") or {}).get("mode") or DEFAULT_MODE
    enable_thinking = mode_enables_thinking(mode)
    force_answer = _tool_calls_this_turn(state["messages"]) >= MAX_TOOL_CALLS

    # 按本轮用户意图预筛工具，闲聊时不绑工具，省掉全部工具 schema 的固定 token
    user_text = _latest_user_text(state["messages"]).lower()
    want = {
        "weather": _hit(user_text, _WEATHER_KWS),
        "map": _hit(user_text, _MAP_KWS),
        "feishu": _hit(user_text, _FEISHU_KWS),
        "browse": _hit(user_text, _BROWSE_KWS),
    }
    all_tools = await _get_all_tools()
    bound_tools = [] if force_answer else _select_tools(all_tools, user_text, want)

    llm = get_llm(model_name, enable_thinking=enable_thinking)
    if bound_tools:
        llm = llm.bind_tools(bound_tools)
    system_prompt = await _get_system_prompt(include_lark=want["feishu"])
    # 身份指令放在历史消息之后，覆盖旧回复里可能出现的其他模型名
    identity = SystemMessage(
        content=IDENTITY_PROMPT.format(model_name=model_name)
    )
    history = _compact_history(list(state["messages"]))
    messages = [SystemMessage(content=system_prompt), *history, identity]
    if force_answer:
        messages.append(SystemMessage(
            content="已连续调用多次工具仍未得到最终答案。现在必须停止调用工具，"
            "直接基于已获取的信息给出最终回答，不要再次调用任何工具。"
        ))
    logger.info(
        "[LLM 输入] 历史压缩 %d 字 -> %d 字（checkpoint 原文未改）；本轮绑定工具 %d/%d；模式=%s(思考=%s)",
        _messages_chars(state["messages"]),
        _messages_chars(history),
        len(bound_tools),
        len(all_tools),
        mode,
        enable_thinking,
    )
    _log_llm_input(model_name, messages, [t.name for t in bound_tools])
    response = await llm.ainvoke(messages)
    return {"messages": [response]}


async def _tools_node(state: MessagesState) -> dict:
    """动态工具执行节点：根据最新消息中的 tool_calls 找到对应的工具执行并返回 ToolMessage。"""
    last_msg = state["messages"][-1]
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {"messages": []}

    all_tools = await _get_all_tools()
    tool_map = {t.name: t for t in all_tools}

    results = []
    for tc in last_msg.tool_calls:
        tool_name = tc.get("name")
        tool_args = tc.get("args") or {}
        call_id = tc.get("id")

        tool = tool_map.get(tool_name)
        if not tool:
            output = f"Error: Tool '{tool_name}' not found or not enabled."
        else:
            try:
                output = await tool.ainvoke(tool_args)
            except Exception as e:
                output = f"Error executing tool '{tool_name}': {e}"

        results.append(ToolMessage(content=str(output), tool_call_id=call_id, name=tool_name))

    return {"messages": results}


class GraphConfig(TypedDict):
    """图运行时配置：thread_id 由 checkpointer 使用，model/mode 为本轮所选模型与模式。"""

    thread_id: str
    model: str
    mode: str


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
