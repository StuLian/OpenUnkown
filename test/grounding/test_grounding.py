"""幻觉闸门 grounding 判定：纯函数 + collector 字段的单元测试。

check_grounding 涉及真实 LLM 调用，不在单测内跑（由验证阶段用真实 ApiKey 人工核对方向）。
"""
from __future__ import annotations

from backend.agent.grounding import (
    EVIDENCE_MAX_CHARS,
    GROUNDING_DISCLAIMER,
    _truncate,
    build_evidence_text,
    parse_verdict,
    should_warn,
)
from backend.config import GROUNDING_CONFIDENCE_THRESHOLD
from backend.tracing import TraceCollector


def _verdict(grounded=True, confidence=0.9, spans=None, reason="ok"):
    return {
        "grounded": grounded,
        "confidence": confidence,
        "ungrounded_spans": spans or [],
        "reason": reason,
    }


def test_parse_verdict_plain():
    v = parse_verdict(
        '{"grounded": false, "confidence": 0.87, "ungrounded_spans": ["x"], "reason": "r"}'
    )
    assert v is not None
    assert v["grounded"] is False
    assert v["confidence"] == 0.87
    assert v["ungrounded_spans"] == ["x"]


def test_parse_verdict_code_fence():
    v = parse_verdict('```json\n{"grounded": true, "confidence": 0.5}\n```')
    assert v is not None and v["grounded"] is True


def test_parse_verdict_trailing_text():
    v = parse_verdict('判定结果：{"grounded": true, "confidence": 0.9} 以上')
    assert v is not None and v["grounded"] is True


def test_parse_verdict_bad_input():
    assert parse_verdict("not json") is None
    assert parse_verdict("") is None
    assert parse_verdict('{"grounded": maybe}') is None
    assert parse_verdict("[1, 2, 3]") is None


def test_parse_verdict_grounded_must_be_bool():
    # grounded 缺省或非 bool → 整个判定作废（宁漏不误伤）
    assert parse_verdict('{"confidence": 0.9}') is None
    assert parse_verdict('{"grounded": "yes", "confidence": 0.9}') is None


def test_parse_verdict_defaults():
    # confidence 缺失/非数值 → 0.0；spans/reason 缺省给安全默认
    v = parse_verdict('{"grounded": false}')
    assert v is not None
    assert v["confidence"] == 0.0
    assert v["ungrounded_spans"] == []
    assert v["reason"] == ""


def test_truncate():
    assert _truncate("short", EVIDENCE_MAX_CHARS) == "short"
    # 关键事实在末尾：保头保尾必须保留末尾事实（二期验证修复的误伤）
    head = "A" * 5000
    tail = "关键事实：北京 25°C 晴"
    long = head + "X" * 2000 + tail
    out = _truncate(long, EVIDENCE_MAX_CHARS)
    assert "关键事实：北京 25°C 晴" in out
    assert "中间省略" in out
    assert len(out) <= EVIDENCE_MAX_CHARS + len("\n...(中间省略 NNNN 字)...\n")


def test_extract_memory_text():
    from backend.agent.grounding import _extract_memory_text

    class _C:
        messages = [
            {"type": "system", "content": "基础提示词"},
            {"type": "system", "kind": "memory", "content": "## 相关记忆\n- 用户住在北京"},
        ]

    assert "用户住在北京" in _extract_memory_text(_C())
    assert _extract_memory_text(type("E", (), {"messages": []})()) == ""


def test_should_warn():
    assert should_warn(_verdict(grounded=False, confidence=0.9)) is True
    assert should_warn(_verdict(grounded=True, confidence=0.9)) is False
    assert (
        should_warn(
            _verdict(grounded=False, confidence=GROUNDING_CONFIDENCE_THRESHOLD - 0.1)
        )
        is False
    )
    assert should_warn({"grounded": False}) is False  # 缺 confidence


def test_build_evidence_text():
    text = build_evidence_text(
        [{"name": "search_hotels", "output": "A B C"}],
        [{"title": "Hotel X", "score": 0.9}],
    )
    assert "search_hotels" in text
    assert "Hotel X" in text
    assert build_evidence_text([], []) == ""


def test_collector_grounding_and_flags():
    c = TraceCollector("u1", "s1", "m", "fast", "bailian", "q")
    assert c.has_flag("memory_injected") is False
    c.add_flag("memory_injected")
    assert c.has_flag("memory_injected") is True
    c.add_flag("hallucination_risk")
    c.set_grounding(_verdict(grounded=False, confidence=0.9, spans=["s"]))
    out = c.finalize()
    assert "hallucination_risk" in out["flags"]
    assert out["grounding"] is not None
    assert out["grounding"]["grounded"] is False


def test_disclaimer_text():
    assert "谨慎采信" in GROUNDING_DISCLAIMER


def test_hallucination_eval_classify():
    from backend.eval.hallucination_eval import _classify

    assert _classify(False, False) == "tp"  # 判无据 + 真无据
    assert _classify(False, True) == "fp"   # 判无据 + 真有据（误伤）
    assert _classify(True, True) == "tn"    # 判有据 + 真有据
    assert _classify(True, False) == "fn"   # 判有据 + 真无据（漏判）
    assert _classify(None, True) == "tn"    # 判定失败 + 真有据 → 未拦截（算放行）
    assert _classify(None, False) == "fn"   # 判定失败 + 真无据 → 未拦截（算漏判）


def test_run_stats_counts():
    import uuid

    from backend.store.db import get_conn
    from backend.store.runs import insert_run, run_stats

    uid = "test-" + uuid.uuid4().hex
    try:
        insert_run(
            {
                "id": "run-" + uuid.uuid4().hex,
                "user_id": uid,
                "session_id": "s",
                "model": "m",
                "mode": "fast",
                "flags": ["hallucination_risk"],
                "grounding": {"grounded": False, "confidence": 0.9, "ungrounded_spans": [], "reason": ""},
                "final_answer": "x",
            }
        )
        insert_run(
            {
                "id": "run-" + uuid.uuid4().hex,
                "user_id": uid,
                "session_id": "s",
                "model": "m",
                "mode": "fast",
                "flags": [],
                "final_answer": "y",
            }
        )
        s = run_stats(uid)
        assert s["total"] == 2
        assert s["grounding_checked"] == 1
        assert s["ungrounded"] == 1
        assert s["hallucination_risk"] == 1
    finally:
        get_conn().execute("DELETE FROM runs WHERE user_id = ?", (uid,))
        get_conn().commit()
