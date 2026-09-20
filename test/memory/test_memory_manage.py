"""记忆管理入口（R10-A）与事实抽取/调度/淘汰（R7）测试。

从 test_memory.py 拆出 —— 该文件已超过 `coding.md` §3 的 300 行上限。
覆盖：越权删除被拒、清空隔离、删会话级联清理、全新库形态回归、
事实抽取/去重/失败降级、上限裁剪、后台调度守卫。
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid

from langchain_core.messages import AIMessage

from backend.agent import memory
from backend.store import memory as store_memory


def _uid() -> str:
    """生成一次性测试用户 id。"""
    return "test-" + uuid.uuid4().hex


def _cleanup(user_id: str) -> None:
    """删除测试用户产生的全部事实记忆。"""
    for fact in store_memory.list_facts(user_id):
        store_memory.delete_fact(fact["id"])


# ---- R10-A：记忆的查看/删除入口 + 删会话级联清理 ----


def test_delete_fact_owned_rejects_other_user():
    """越权删除他人记忆必须被拒（返回 False），且原记忆仍在。"""
    owner, other = _uid(), _uid()
    try:
        fid = store_memory.add_fact(owner, "属于 owner 的事实", [1.0, 0.0])
        assert store_memory.delete_fact_owned(other, fid) is False
        assert store_memory.count_facts(owner) == 1
        assert store_memory.delete_fact_owned(owner, fid) is True
        assert store_memory.count_facts(owner) == 0
    finally:
        _cleanup(owner)
        _cleanup(other)


def test_delete_all_facts_only_own():
    """一键清空只影响本人，不触碰他人记忆。"""
    user_a, user_b = _uid(), _uid()
    try:
        store_memory.add_fact(user_a, "A 的事实", [1.0, 0.0])
        store_memory.add_fact(user_b, "B 的事实", [0.0, 1.0])
        assert store_memory.delete_all_facts(user_a) == 1
        assert store_memory.count_facts(user_a) == 0
        assert store_memory.count_facts(user_b) == 1  # 他人不受影响
    finally:
        _cleanup(user_a)
        _cleanup(user_b)


def test_delete_session_cascades_summary_but_keeps_facts():
    """删会话应级联清掉该会话的滚动摘要；跨会话的 fact 不受影响（R10 附带缺陷回归）。"""
    from backend import store
    from backend.store.db import _lock, get_conn

    user, session = _uid(), "sess-" + uuid.uuid4().hex
    try:
        store.create_session(user, session, "标题")
        store_memory.save_summary(user, session, "会话摘要")
        store_memory.add_fact(user, "跨会话事实", [1.0, 0.0])
        assert store_memory.load_summary(user, session) == "会话摘要"

        assert store.delete_session(user, session) is True

        assert store_memory.load_summary(user, session) == ""  # 摘要被级联清理
        assert store_memory.count_facts(user) == 1  # fact 保留
    finally:
        _cleanup(user)
        with _lock:
            conn = get_conn()
            conn.execute("DELETE FROM memories WHERE user_id = ?", (user,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session,))
            conn.commit()


def test_delete_session_survives_missing_checkpoint_tables(monkeypatch):
    """B1 回归：全新库（checkpoints/writes 表不存在）删会话不得抛错，且级联清理仍要执行。

    用内存库替换 sessions 模块的 get_conn，精确模拟「sessions/memories 存在、
    checkpoints/writes 不存在」的全新库形态，不触碰真实开发库。
    """
    from backend.store import sessions as sessions_mod

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, title TEXT,"
        " created_at REAL, updated_at REAL)"
    )
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, user_id TEXT, session_id TEXT,"
        " kind TEXT, content TEXT, embedding TEXT, created_at REAL, updated_at REAL)"
    )
    conn.execute("INSERT INTO sessions VALUES ('s1','u1','t',0,0)")
    conn.execute("INSERT INTO memories VALUES ('m1','u1','s1','summary','摘要',NULL,0,0)")
    conn.commit()

    monkeypatch.setattr(sessions_mod, "get_conn", lambda: conn)

    # 不抛异常，且返回删除成功（旧实现在此会因 checkpoints 不存在而抛 OperationalError）
    assert sessions_mod.delete_session("u1", "s1") is True
    # 关键：级联清理没有被前面的异常吞掉
    left = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE session_id = 's1'"
    ).fetchone()[0]
    assert left == 0


# ---- R7：extract_facts / _evict_overflow / schedule_extraction ----


class _FakeLLM:
    """替身 LLM：ainvoke 直接返回给定文本，避免真实调用模型。"""

    def __init__(self, reply: str):
        self._reply = reply

    async def ainvoke(self, _messages):
        return AIMessage(content=self._reply)


def test_extract_facts_parses_and_stores(monkeypatch):
    """extract_facts：抽取 → 向量化 → 入库 全链路（mock LLM 与向量化）。"""
    user = _uid()
    try:
        monkeypatch.setattr(
            memory, "get_llm", lambda *a, **k: _FakeLLM("1. 用户在北京\n2. 喜欢简洁回答")
        )
        # 两条事实给正交向量，避免被去重规则判为重复
        monkeypatch.setattr(
            memory,
            "embed_texts",
            lambda texts, text_type, api_key: [
                [1.0, 0.0, 0.0] if i == 0 else [0.0, 1.0, 0.0]
                for i in range(len(texts))
            ],
        )
        asyncio.run(memory.extract_facts(user, "问题", "回答", "k", "http://x"))

        contents = {f["content"] for f in store_memory.list_facts(user)}
        assert "用户在北京" in contents
        assert "喜欢简洁回答" in contents
    finally:
        _cleanup(user)


def test_extract_facts_skips_similar_existing_fact(monkeypatch):
    """extract_facts：与已有记忆高度相似时不重复入库（去重阈值生效）。"""
    user = _uid()
    try:
        store_memory.add_fact(user, "用户在北京", [1.0, 0.0, 0.0])
        monkeypatch.setattr(memory, "get_llm", lambda *a, **k: _FakeLLM("用户常住北京"))
        monkeypatch.setattr(
            memory, "embed_texts", lambda texts, text_type, api_key: [[1.0, 0.0, 0.0]]
        )
        asyncio.run(memory.extract_facts(user, "问题", "回答", "k", "http://x"))
        # 相似度 1.0 >= FACT_DEDUP_SIM(0.92) → 跳过，不新增
        assert store_memory.count_facts(user) == 1
    finally:
        _cleanup(user)


def test_extract_facts_swallows_llm_error(monkeypatch):
    """extract_facts：LLM 抛错时静默失败，不冒泡（记忆是增强，不阻塞主流程）。"""

    class _BoomLLM:
        async def ainvoke(self, _messages):
            raise RuntimeError("model down")

    monkeypatch.setattr(memory, "get_llm", lambda *a, **k: _BoomLLM())
    asyncio.run(memory.extract_facts(_uid(), "问题", "回答", "k", "http://x"))


def test_evict_overflow_keeps_newest(monkeypatch):
    """_evict_overflow：超过上限时删除最旧的，保留最新的 N 条。"""
    user = _uid()
    try:
        monkeypatch.setattr(memory, "MEMORY_MAX_FACTS", 3)
        for i in range(5):
            store_memory.add_fact(user, f"事实{i}", [1.0, 0.0])
            time.sleep(0.002)  # 保证 created_at 严格递增，消除排序歧义
        memory._evict_overflow(user)
        assert store_memory.count_facts(user) == 3
        assert {f["content"] for f in store_memory.list_facts(user)} == {
            "事实4",
            "事实3",
            "事实2",
        }
    finally:
        _cleanup(user)


def test_schedule_extraction_without_loop_is_noop():
    """schedule_extraction：同步上下文（无事件循环）直接返回，不抛错、不留未 await 协程。"""
    memory.schedule_extraction("u", "问题", "回答", "key", "http://x")


def test_schedule_extraction_skips_when_no_api_key():
    """schedule_extraction：**在事件循环内**，无 ApiKey / 空回答应直接跳过（不创建任务）。

    必须在循环内断言：同步上下文下 `get_running_loop()` 会先失败而提前返回，
    守卫是否生效便无从体现 —— 那正是上一版用例同义反复（突变后仍 PASS）的原因。
    """

    async def _run() -> tuple[int, int]:
        before = len(memory._background)
        memory.schedule_extraction("u", "问题", "回答", "", "http://x")       # 无 ApiKey
        memory.schedule_extraction("u", "问题", "   ", "key", "http://x")    # 空回答
        return before, len(memory._background)

    before, after = asyncio.run(_run())
    assert after == before
