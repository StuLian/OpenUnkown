# test_plan · 20260923-111235-hallucination-gate

> 对应 proposal 第 2 节验收标准 + 第 7 节验证计划。本文件列「打算怎么验」，实际结果见 `test_report.md`。

## 一、机器可查（自动）

| 项 | 命令 | 期望 |
|---|---|---|
| 单元测试 | `.venv/bin/python -m pytest test/grounding/ -q` | 11 passed |
| 全量回归 | `.venv/bin/python -m pytest test/ -q` | 全绿（含存量 53） |
| import/启动 | `.venv/bin/python -c "import backend.main; from backend.api.streaming import stream_answer, resume_answer"` | OK |
| prompt 结构回归 | `.venv/bin/python -m backend.eval.prompt_eval` | 全通过（版本 1.1.0） |

## 二、验收标准逐条核对（对照 proposal §2）

1. 无证据事实问答 → trace 打 `hallucination_risk` flag：靠 `apply_grounding` 内 `collector.add_flag("hallucination_risk")` + 单测 `test_collector_grounding_and_flags`。
2. 高风险回答附加「未经检索/工具验证」免责话术：靠 `turn.py` 收口 `yield {"delta": GROUNDING_DISCLAIMER}`，单测 `test_disclaimer_text`。
3. 有工具/RAG/记忆支撑的回答不触发判定：靠 `should_run_grounding` 触发条件 + 单测 `test_should_run_grounding`。
4. 判定结果落 trace：靠 collector `grounding` 字段 + `runs.get_run` 返回，单测 `test_collector_grounding_and_flags`。
5. 判定失败降级不拦截：靠 `parse_verdict` 返回 None + `check_grounding` try/except + 单测 `test_parse_verdict_bad_input` / `test_parse_verdict_grounded_must_be_bool`。
6. 判定解析/触发/降级/flag 各有 pytest 覆盖：`test/grounding/test_grounding.py` 11 条。

## 三、真实 API 人工核对（判定方向）

用 `resolve_api_key` 取真实 Key，跑「无据 vs 有据」各 ≥2 例，人工看判定方向是否对：

- 无据：`埃菲尔铁塔在伦敦`、`珠穆朗玛峰在非洲` → 期望 grounded=false
- 有据/常识：`1+1=2`、`水的化学式是 H2O` → 期望 grounded=true
- 拒答/转述用户：`我告诉你我叫小明，你说我叫什么` → 期望 grounded=true（转述用户原文不算无据）

## 四、独立验证 agent 需做的事

1. 跑上面「机器可查」四命令，记录真实输出。
2. 对照 proposal §2 六条验收标准逐条打 ✓/✗。
3. 跑真实 API 判定方向核对（若无 Key 则标注「未能验」并按 review.md 打黄）。
4. 按 `review.md` 打红黄绿，写 `test_report.md`；发现真 bug 就停在红等修复。

## 五、补充验证（trace 呈现 + 幻觉评测，2026-09-23）

| 项 | 命令 | 期望 |
|---|---|---|
| 幻觉评测基线 | `EVAL_API_KEY=<key> .venv/bin/python -m backend.eval.hallucination_eval` | precision/recall/F1 汇总 + 逐条明细 |
| 统计闭环 | `.venv/bin/python -m pytest test/grounding/ -q` | 含 `_classify` + `run_stats` 共 13 passed |
| 前端类型 | `cd frontend && npm run typecheck` | 无报错 |
| 前端构建 | `cd frontend && npm run build` | 成功（仅存量 chunk-size 告警） |
| /stats 接口 | `GET /api/runs/stats`（需登录）| 返回 total/grounding_checked/ungrounded/hallucination_risk |

真实 ApiKey 评测基线：**19 例 F1=1.0（0 误伤 0 漏判）**。
