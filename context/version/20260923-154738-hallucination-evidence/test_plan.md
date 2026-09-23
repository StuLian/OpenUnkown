# test_plan · 20260923-154738-hallucination-evidence

> 对应 proposal §2 验收标准 + §7 验证计划。

## 一、机器可查

| 项 | 命令 | 期望 |
|---|---|---|
| 单元测试 | `.venv/bin/python -m pytest test/grounding/ -q` | 14 passed（含 test_truncate） |
| 全量回归 | `.venv/bin/python -m pytest test/ -q` | 67 passed |
| import/启动 | `.venv/bin/python -c "import backend.main; import backend.agent.grounding"` | OK |
| prompt 结构 | `.venv/bin/python -m backend.eval.prompt_eval` | 全部通过（版本 1.2.0） |
| 幻觉评测 | `EVAL_API_KEY=<key> .venv/bin/python -m backend.eval.hallucination_eval` | 26 例，precision/recall/F1 |

## 二、验收标准逐条核对（对照 proposal §2）

1. 有工具/RAG 时也判 + 证据真实传入：`apply_grounding` 不再短路 + `build_evidence_text` 拼证据，端到端冒烟验证。
2. 「与证据矛盾/编造」判 grounded=false + 打标 + 免责：端到端冒烟「25°C 晴 → 答 30°C 暴雨」→ 免责+打标 True。
3. 「忠于证据」不误伤：冒烟「25°C 晴 → 答 25°C 晴」→ False；评测 3 例答对均 TN。
4. 无据场景不回退：评测原 19 例仍全对（TP=7 等并入 26 例无错判）。
5. 证据超长截断：`test_truncate`。
6. 判定失败降级 + 总开关：`check_grounding` try/except + `GROUNDING_ENABLED`（v1 已验，未动）。
7. 评测集扩充后基线：26 例 F1=1.0。

## 三、独立验证 agent 需做的事

1. 跑上面「机器可查」五命令，记录真实输出。
2. 对照 proposal §2 七条逐条打 ✓/✗。
3. 用真实 ApiKey 复跑评测 + 端到端冒烟（有据但答错 / 有据答对 / 无据三例）。
4. 按 `review.md` 打红黄绿，写 `test_report.md`。
