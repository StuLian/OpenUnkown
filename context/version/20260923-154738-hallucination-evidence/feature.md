# feature · 20260923-154738-hallucination-evidence（幻觉闸门二期：有据也判）

> 状态：已实施（独立验证 🟡→修复→🟢 绿）
> 提交 hash：633dbd1
> 关联 proposal：本目录 `proposal.md`（已确认）

## 一、`backend/agent/grounding.py`

- 删除 `should_run_grounding`（触发从「无工具+无RAG」放宽为「答案非空即判」）。
- 新增 `EVIDENCE_MAX_CHARS=6000` + `_truncate()`：证据超长截断，防工具返回（如 shell 20KB）顶破判定预算。
- `apply_grounding`：不再按工具/RAG 短路；把 `build_evidence_text(tool_outputs, retrieved_docs)` + 记忆文本拼成 evidence（各段截断），传给判定模型。
- `GROUNDING_DISCLAIMER` 改为通用话术「以上回答可能存在事实性错误，请谨慎采信」（同时覆盖无据 + 与证据不符）。

## 二、`backend/agent/prompts.py`

- `GROUNDING_PROMPT` 判定规则 2 拆成两分支：证据为空 → 「查无来源」判无据；证据非空 → 「与证据矛盾 / 证据中不存在」判无据。
- `PROMPT_VERSION` 1.1.0 → **1.2.0**。

## 三、评测

- `eval/hallucination_eval.py`：`check_grounding` 传入 `case.get("evidence", "")`。
- `datasets/hallucination_cases.json`：新增 7 例「有据」样例（4 例答错 + 3 例答对），总 26 例。

## 四、测试

- `test_grounding.py`：删 `test_should_run_grounding`（函数已删），新增 `test_truncate`。

## 五、机器验证（本 agent 已跑）

```
pytest test/grounding/ -q   -> 14 passed
pytest test/ -q             -> 67 passed, 1 warning（pydantic 存量告警）
prompt_eval                 -> 全部通过（版本 1.2.0）
幻觉评测（真实 ApiKey，26 例）-> precision=1.000 recall=1.000 F1=1.000（TP=11 FP=0 TN=15 FN=0）
端到端冒烟：有据但答错 → 免责提示+打标 True；有据且答对 → False（不误伤）
```

## 六、修复记录（2026-09-23，独立验证 🟡 后修复）

独立验证抓出 2 个问题，均已修：

1. **`_truncate` 砍尾误伤（真 bug）**：原实现只保前 6000 字，关键事实在证据末尾时被切掉，导致忠实回答被误判为无据。改为「保头 2/3 + 保尾 1/3、砍中间」；`test_truncate` 补「尾部关键事实必须保留」语义断言。
2. **「8848 vs 8848.86」golden 偏严**：合理约等于不是幻觉，改为清晰矛盾例（「位于非洲」vs 证据「位于亚洲」）。

复验：pytest 67 passed；26 例评测 P/R/F1=1.0、0 错判；端到端复现「关键事实在证据末尾」场景已不误伤。打灯 🟢。
