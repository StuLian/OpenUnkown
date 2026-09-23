# feature · 20260923-111235-hallucination-gate（幻觉闸门：无据不答）

> 状态：已实施（待验证）
> 关联 proposal：本目录 `proposal.md`（已确认）

## 一、新增 `backend/agent/grounding.py`（约 160 行）

生成后 grounding 判定的纯逻辑，不碰 trace 落库与流式收口：

- `should_run_grounding(has_tool_calls, has_retrieved_docs, memory_injected)`：触发条件——无工具调用 + 无 RAG 召回 + 无记忆注入才判。
- `should_warn(verdict)`：`grounded=false` 且 `confidence ≥ GROUNDING_CONFIDENCE_THRESHOLD` 才降级（宁漏不误伤）。
- `build_evidence_text(tool_outputs, retrieved_docs)`：拼判定证据文本。
- `parse_verdict(text)`：JSON 解析（剥 ```json 围栏、截首尾大括号、缺省字段给安全默认；`grounded` 非 bool 则作废）。
- `check_grounding(query, answer, evidence, api_key, base_url)`：调 `qwen-turbo` 判定，失败返回 None。
- `apply_grounding(collector, answer, config)`：streaming 收口只调这一个入口——触发→判定→`set_grounding`→`add_flag("hallucination_risk")`→返回免责提示。

## 二、prompt / 配置 / trace / 存储

- `prompts.py`：新增 `GROUNDING_PROMPT`（判定层）；`PROMPT_VERSION` 1.0.0 → **1.1.0**。
- `config.py`：新增 `GROUNDING_ENABLED=True` / `GROUNDING_MODEL="qwen-turbo"` / `GROUNDING_CONFIDENCE_THRESHOLD=0.7`。
- `tracing/collector.py`：新增 `grounding` 字段 + `set_grounding()` + `has_flag()`，`finalize()` 输出 `grounding`。
- `store/db.py`：runs 表幂等迁移加 `grounding TEXT` 列。
- `store/runs.py`：`insert_run` 落 `grounding`（JSON），`get_run` 返回 `grounding`。

## 三、`streaming.py` 拆包（合规 ≤300 行）

原 `backend/api/streaming.py`（356 行，本已超限）拆为 `backend/api/streaming/` 包：

- `__init__.py`（198 行）：`stream_answer` / `resume_answer` / `sse_event` / `_build_config`，对外 API 不变（`from backend.api.streaming import stream_answer, resume_answer` 兼容）。
- `turn.py`（143 行）：`stream_turn`（原 `_stream_turn`）+ `_persist_trace`；收口处新增幻觉闸门调用（`apply_grounding` + 免责 `delta`）。
- `confirm.py`（51 行）：`pending_confirm` / `drain_pending_confirm`（原 `_pending_confirm` / `_drain_pending_confirm`）。

同时去掉原 streaming.py 里未使用的 `message_to_dict` import。

## 四、测试

- 新增 `test/grounding/test_grounding.py`（11 条）：判定 JSON 解析（围栏/尾随文本/坏 JSON/字段缺省/grounded 非 bool 作废）、触发条件、`should_warn`、证据拼接、collector 的 `grounding`/`has_flag`/`finalize`、免责文案。

## 五、机器验证（本 agent 已跑）

```
.venv/bin/python -c "import backend.main / backend.api.streaming / backend.agent.grounding"  ->  OK
.venv/bin/python -m pytest test/ -q                                                          ->  64 passed, 1 warning（pydantic 存量告警）
.venv/bin/python -m backend.eval.prompt_eval                                                  ->  全部通过（版本 1.1.0）
真实 API 冒烟（qwen-turbo，2 例）：
  「埃菲尔铁塔在伦敦」 -> grounded=false / confidence=1.0 / should_warn=True
  「1+1=2」             -> grounded=true  / confidence=1.0 / should_warn=False
```

## 六、补充：trace 呈现 + 幻觉评测基线（2026-09-23 追加）

- `backend/store/runs.py`：新增 `run_stats(user_id)`（总轮数 / 判定数 / 无据数 / 幻觉风险标记数，SQL 用 LIKE 匹配 `"grounded": false` 与 `"hallucination_risk"`）。
- `backend/api/routers/runs.py`：新增 `GET /api/runs/stats`（注册在 `/{run_id}` 之前，避免被吞）。
- `backend/eval/hallucination_eval.py`：评测运行器（调 `check_grounding`，按 `_classify` 归 tp/fp/tn/fn，汇总 precision/recall/F1/误伤率/漏判率）。
- `backend/eval/datasets/hallucination_cases.json`：19 组人工标好 golden（7 无据幻觉 + 12 有据/常识/转述/拒答）。
- `backend/eval/report.py`：新增 `render_hallucination_report`。
- 前端：`types.ts`（GroundingVerdict / RunStats / RunDetail.grounding）、`endpoints.ts`（fetchRunStats）、`RunDetail.tsx`（渲染「幻觉闸门判定」段）、`TracesPanel.tsx`（顶部统计条）、`styles.css`（.trace-stats）。

**评测基线（真实 ApiKey，19 例）**：`precision=1.000 / recall=1.000 / F1=1.000`，误伤率 0、漏判率 0（TP=7 FP=0 TN=12 FN=0）。

**测试**：`test_grounding.py` 新增 2 条（`_classify` 六分支 + `run_stats` 统计闭环），全量 **66 passed**。

## 七、修复记录（2026-09-23，虚绿 bug）

**问题**：触发条件原为「无工具 + 无 RAG + 无记忆注入」才判。但实测几乎每轮都注入记忆（用户已积累记忆），导致 `memory_injected=True` → 判定**永远被跳过**，闸门形同虚设（用户反馈「trace 里没看见幻觉卡片」）。

**根因**：把「记忆」错当成「证据」。记忆是用户画像/偏好，不支撑具体事实断言。

**修复**：
- `should_run_grounding` 去掉 `memory_injected` 参数，触发条件只判「无工具 + 无 RAG」。
- `apply_grounding` 新增 `_extract_memory_text()`，把 `kind=memory` 的注入记忆作为**证据**喂给判定模型，避免「复述记忆」（如「你住在北京」）被误伤。

**验证**：`test_should_run_grounding` / `test_extract_memory_text` 更新+新增；真实 API 冒烟：无据幻觉（有记忆注入）→ 出免责提示 ✅；复述记忆 → 不出提示 ✅。全量 **67 passed**。
