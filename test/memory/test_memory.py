"""Phase 2 记忆系统测试：预算判断、消息组装、事实解析、召回排序、存储闭环。

不依赖模型 API：召回排序用 monkeypatch 让 embed_texts 返回固定向量，验证排序与阈值。
存储用例使用随机 user_id 并在结束时清理，避免污染开发库。
"""
from __future__ import annotations

import asyncio
import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent import memory
from backend.agent.context import compact_history
from backend.store import memory as store_memory


def _uid() -> str:
    """生成一次性测试用户 id。"""
    return "test-" + uuid.uuid4().hex


def _cleanup(user_id: str) -> None:
    """删除测试用户产生的全部记忆记录。"""
    for fact in store_memory.list_facts(user_id):
        store_memory.delete_fact(fact["id"])


def test_should_summarize_respects_budget():
    assert memory.should_summarize([HumanMessage(content="你好")]) is False
    huge = [HumanMessage(content="x" * (memory.MAX_HISTORY_CHARS + 1))]
    assert memory.should_summarize(huge) is True


def test_parse_facts_strips_bullets_and_noise():
    text = "1. 用户在北京\n- 喜欢简洁回答\n\n*   \n2) 这是很长的一条" + "啊" * 300
    facts = memory.parse_facts(text)
    assert "用户在北京" in facts
    assert "喜欢简洁回答" in facts
    assert all(len(f) <= 200 for f in facts)


def test_build_memory_text_sections():
    assert memory.build_memory_text("", []) == ""
    text = memory.build_memory_text("早前聊过天气", ["用户在北京"])
    assert "## 相关记忆" in text and "用户在北京" in text
    assert "## 历史对话摘要" in text and "早前聊过天气" in text


def test_compact_history_truncates_old_tool_output():
    long_tool = ToolMessage(
        content="y" * 1000, tool_call_id="t1", name="search_hotels"
    )
    msgs = [long_tool, HumanMessage(content="q"), AIMessage(content="a")]
    out = compact_history(msgs)
    # 未超过 KEEP_TAIL 时原样保留
    assert out[0].content == long_tool.content
    # 构造超过 KEEP_TAIL 的历史，最老的超长工具结果应被截断
    many = [long_tool] + [HumanMessage(content=f"m{i}") for i in range(20)]
    compacted = compact_history(many)
    assert "已截断" in compacted[0].content
    assert len(compacted[0].content) < 1000


def test_summary_store_roundtrip():
    user, session = _uid(), "sess-1"
    assert store_memory.load_summary(user, session) == ""
    store_memory.save_summary(user, session, "第一版摘要")
    assert store_memory.load_summary(user, session) == "第一版摘要"
    store_memory.save_summary(user, session, "第二版摘要")
    assert store_memory.load_summary(user, session) == "第二版摘要"
    # 清理 summary 行
    from backend.store.db import _lock, get_conn

    with _lock:
        get_conn().execute(
            "DELETE FROM memories WHERE user_id = ? AND kind = 'summary'", (user,)
        )
        get_conn().commit()


def test_fact_store_add_list_count_delete():
    user = _uid()
    try:
        assert store_memory.count_facts(user) == 0
        fid = store_memory.add_fact(user, "用户是后端工程师", [0.1, 0.2, 0.3])
        assert store_memory.count_facts(user) == 1
        facts = store_memory.list_facts(user)
        assert facts[0]["id"] == fid
        assert facts[0]["content"] == "用户是后端工程师"
        assert facts[0]["embedding"] == [0.1, 0.2, 0.3]
        store_memory.delete_fact(fid)
        assert store_memory.count_facts(user) == 0
    finally:
        _cleanup(user)


def test_recall_ranks_by_cosine_and_filters_low_similarity(monkeypatch):
    user = _uid()
    try:
        store_memory.add_fact(user, "高相关事实", [1.0, 0.0, 0.0])
        store_memory.add_fact(user, "正交不相关事实", [0.0, 1.0, 0.0])
        # 让 query 向量与第一条同向、与第二条正交
        monkeypatch.setattr(
            memory, "embed_texts", lambda texts, text_type, api_key: [[1.0, 0.0, 0.0]]
        )
        result = asyncio.run(memory.recall_facts(user, "任意问题", "fake-key"))
        assert result == ["高相关事实"]
    finally:
        _cleanup(user)


def test_recall_returns_empty_without_facts(monkeypatch):
    monkeypatch.setattr(
        memory, "embed_texts", lambda texts, text_type, api_key: [[1.0, 0.0, 0.0]]
    )
    assert asyncio.run(memory.recall_facts(_uid(), "问题", "fake-key")) == []


# ---- 以下为 R1–R4 缺陷的回归用例 ----


def test_message_text_ignores_image_base64():
    """R2：多模态消息的图片 base64 不能算进历史字数预算。"""
    msg = HumanMessage(content=[
        {"type": "text", "text": "看看这张图"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + "A" * 5000},
        },
    ])
    assert memory.history_chars([msg]) < 50
    assert memory.should_summarize([msg]) is False


def test_parse_facts_keeps_leading_digits():
    """R4/N1：行首正文数字、小数、负号、顿号连接的数字都不能被当成列表标记剥掉。"""
    facts = memory.parse_facts(
        "2024年搬到北京\n"      # 年份
        "3个孩子的父亲\n"        # 数量
        "3.14是圆周率\n"        # 小数
        "-5度以下偏好\n"        # 负号
        "2、3线城市\n"          # 顿号连接
        "- 喜欢简洁回答\n"       # 真列表项（有空白）
        "1. 用户是工程师"        # 真序号（有空白）
    )
    for kept in [
        "2024年搬到北京",
        "3个孩子的父亲",
        "3.14是圆周率",
        "-5度以下偏好",
        "2、3线城市",
    ]:
        assert kept in facts, f"正文被误剥: {kept}"
    assert "喜欢简洁回答" in facts
    assert "用户是工程师" in facts


def test_recall_returns_empty_when_embedding_empty(monkeypatch):
    """R1：向量化返回空列表时不能抛 IndexError，应降级为不注入。"""
    user = _uid()
    try:
        store_memory.add_fact(user, "某事实", [1.0, 0.0])
        monkeypatch.setattr(memory, "embed_texts", lambda texts, text_type, api_key: [])
        assert asyncio.run(memory.recall_facts(user, "问题", "k")) == []
    finally:
        _cleanup(user)


def test_recall_swallows_store_errors(monkeypatch):
    """R1：召回内部任何异常都不得冒泡（此处让 list_facts 抛错）。"""
    def _boom(_user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(memory, "list_facts", _boom)
    assert asyncio.run(memory.recall_facts(_uid(), "问题", "k")) == []


def test_assemble_skips_summary_when_no_old_messages(monkeypatch):
    """R3：条数未超过保留窗口时不得调用摘要（否则会伪造摘要并落库）。"""
    from backend.agent import context as ctx

    calls = {"n": 0}

    async def _fake_summarize(*args, **kwargs):
        calls["n"] += 1
        return "不该被调用"

    async def _fake_recall(*args, **kwargs):
        return []

    monkeypatch.setattr(ctx, "summarize_history", _fake_summarize)
    monkeypatch.setattr(ctx, "recall_facts", _fake_recall)

    # 单条超长消息：字数超预算但条数未超过 SUMMARY_KEEP_TAIL
    msgs = [HumanMessage(content="x" * (memory.MAX_HISTORY_CHARS + 10))]
    _, info = asyncio.run(
        ctx.assemble_model_messages(
            state_messages=msgs,
            system_prompt="sys",
            identity_text="id",
            user_id=_uid(),
            session_id="sess-guard",
            query="q",
            api_key="k",
            base_url="http://x",
            force_answer=False,
        )
    )
    assert calls["n"] == 0
    assert info["summarized"] is False
