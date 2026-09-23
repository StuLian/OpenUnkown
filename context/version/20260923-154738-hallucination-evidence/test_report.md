# test_report · 20260923-154738-hallucination-evidence（幻觉闸门二期：有据也判）

> 独立验证 agent 结论。本报告所有机器命令均由验证 agent 亲自在项目 `.venv` 下执行，未采信实现者 feature.md 自述输出。
> 最终打灯：**🟡 黄**（见 §5）。

---

## 1. 机器验证记录（真实输出，agent 亲跑）

| # | 命令 | 真实输出 | 期望 | 结果 |
|---|------|---------|------|------|
| 1 | `.venv/bin/python -m pytest test/grounding/ -q` | `14 passed in 0.45s` | 14 passed（含 test_truncate） | ✅ |
| 2 | `.venv/bin/python -m pytest test/ -q` | `67 passed, 1 warning in 0.73s`（warning 为 pydantic `lifespan` 前向引用，**存量告警**，与本次无关） | 67 passed | ✅ |
| 3 | `.venv/bin/python -c "import backend.main; import backend.agent.grounding"` | `IMPORT OK` | import OK | ✅ |
| 4 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.2.0` + 四层 `[✓]`（身份/行为/格式/RAG引用）+ `结果：全部通过` | 版本 1.2.0 全通过 | ✅ |
| 5 | `EVAL_API_KEY=<key> .venv/bin/python -m backend.eval.hallucination_eval --json-out /tmp/v2_report.json` | 见 §3，26 例 `precision=1.000 recall=1.000 F1=1.000`（TP=11 FP=0 TN=15 FN=0） | 26 例基线可复现 | ✅ |

补充人工核对（验证 agent 自行加验）：

| 检查 | 结果 |
|---|---|
| `wc -l` 全部改动文件 | `grounding.py` 171 / `prompts.py` 136 / `hallucination_eval.py` 132 / `test_grounding.py` 179 行 → **全部 ≤300 行** ✅ |
| `should_run_grounding` 残留引用 | `grep -rn "should_run_grounding" backend/ test/` → 无残留，删除干净 ✅ |
| `GROUNDING_PROMPT.format(...)`（含 `{`/`}`/引号/中文证据 3 组样本） | 3 组均 format OK，无 KeyError，渲染后 JSON 模板还原为 `{"grounded": ...}` → **`{{}}` 转义正确** ✅ |
| `GROUNDING_ENABLED` 一键开关 wiring | `config.py` L71 `GROUNDING_ENABLED = True`；`apply_grounding` 首行 `if not GROUNDING_ENABLED ... return None` → **仍是一键总开关** ✅ |
| 证据 wiring（`record_tool_output`/`record_retrieved_docs`） | `graph.py` L302-303 每次工具执行都 `record_tool_output(call_id, name, str(output))`（**存全量、不截断**）；`hotels.py` L54 `record_retrieved_docs(results)` → 证据来源真实可用 ✅ |

---

## 2. 验收标准七条逐条核对（proposal §2）

1. **[✓] 有工具/RAG 证据时也会跑判定，证据真实传入判定模型**
   证据：`apply_grounding`（grounding.py L141-171）不再按「无工具+无RAG」短路，只要 `GROUNDING_ENABLED` 且 answer 非空即判；`build_evidence_text(tool_outputs, retrieved_docs)` 拼证据 + `_extract_memory_text` 并入。§3 冒烟 (a) 实测 judge 的理由**明确引用了证据内容**（「与提供的证据（北京 25°C，晴）矛盾」），证明证据真实传入、非空串。

2. **[✓] 「与证据矛盾/编造证据外事实」判 grounded=false + 打标 + 免责**
   证据：§3 冒烟 (a) 证据 25°C 晴 → 答 30°C 暴雨，实测 `grounded=False conf=1.0`、`hallucination_risk` flag=True、`disclaimer=True`。评测 4 例有据答错全部 TP（见 §3）。

3. **[⚠️ 常规场景 ✓，边界有缺口] 「忠于证据」不被误伤（含合理总结/省略）**
   常规场景：§3 冒烟 (b) 证据 25°C 晴 → 答 25°C 晴，实测 `grounded=True`、无 flag、无免责 ✅；评测 3 例有据答对全部 TN ✅。**边界缺口**：证据 >6000 字且关键事实落在末尾时，`_truncate` 砍尾导致误伤（已复现，见 §4 问题 1）——因「标注不拒答」兜底，误伤只多一条免责、不阻塞，但确与「不误伤」目标有张力。

4. **[✓] 无据场景行为不回退（v1 用例仍通过）**
   证据：原 19 例（7 条 golden=false + 12 条 golden=true）在 26 例评测中**全部判对**（7 TP + 12 TN，零错判，见 §3 明细）。冒烟 (c) 无证据 + 「珠峰在非洲」→ 免责+打标 True ✅。

5. **[⚠️ 部分达成] 证据超长时截断，不顶破判定模型 token 预算**
   「不顶破预算」：`_truncate` 生效，`test_truncate` 通过，实测 6219 字证据截断到 6014 字 ✅。**但截断策略是「砍尾」（保留前 6000 字）**，会把落在末尾的关键事实切掉导致误判（§4 问题 1）。proposal §6.3 自述「优先喂检索召回 + 工具返回的关键字段」，实现**未做关键字段优先**，只做了朴素砍头截断。

6. **[✓] 判定失败降级「不拦截只告警」；GROUNDING_ENABLED 仍是一键总开关**
   证据：`check_grounding` 对 LLM 调用与 `parse_verdict` 均 try/except，失败返回 None；`apply_grounding` 对 None verdict 直接 return None。`GROUNDING_ENABLED` 见 §1 补充核对，未动、仍是一键总开关。

7. **[✓] 评测集扩充后 precision/recall/F1 有回归基线**
   证据：26 例（19 存量 + 7 新增）真实 API 复跑 `precision=1.000 / recall=1.000 / F1=1.000`（§3），与 feature.md 自述一致。

---

## 3. 真实 API 复跑结果

用 `resolve_api_key("usr-b40019392234", "bailian")` 从 `users`+`user_api_keys` 表解析真实 Key（ciphertext len 248 → 解密 len 115，前缀 `sk-ws-`），对 26 例评测集 + 4 例端到端冒烟全部实测（qwen-turbo）。

### 3.1 幻觉评测（26 例）

```
幻觉闸门评测  cases=26  TP=11 FP=0 TN=15 FN=0
  precision = 1.000（误伤率 = 0.000）
  recall    = 1.000（漏判率 = 0.000）
  F1        = 1.000
```

- **7 条新增「有据」样例**：4 例答错全部抓对（30°C暴雨 vs 25°C晴、500 vs 200 美元×2、8848 vs 8848.86）；3 例答对全部放行（含 1 例「合理总结/省略」——「主要提供泳池，价格为每晚 200 美元」判 TN）。
- **19 条 v1 存量样例**：7 例无据幻觉全部 TP，12 例常识/转述/拒答全部 TN，**零回退**。
- **8848 vs 8848.86 那例**：`golden=false, pred=false, conf=1.0`，判定模型理由「数值与证据中的 8848.86 米不一致」→ 本轮判为 TP。**但 golden 口径本身偏严、且依赖判定模型的严格程度**（见 §4 问题 2）。

### 3.2 端到端冒烟（走 `apply_grounding` 全链路，非仅 `check_grounding`）

| 例 | query / answer / 证据 | grounded | flag | disclaimer | 期望 | 结果 |
|---|---|---|---|---|---|---|
| (a) 有据但答错 | 今天北京天气？ / 30°C 暴雨 / [get_weather] 北京 25°C，晴 | False | True | True | 免责+打标 | ✅ |
| (b) 有据且答对 | 今天北京天气？ / 25°C 晴 / [get_weather] 北京 25°C，晴 | True | False | False | 不误伤 | ✅ |
| (c) 无据事实幻觉 | 珠峰在哪？ / 珠峰在非洲 / （无） | False | True | True | 免责 | ✅ |
| (d) 纯闲聊 | 你好 / 你好呀！ / （无） | True | False | False | 不误伤 | ✅ |

`apply_grounding` 全链路（证据组装→截断→`check_grounding`→`set_grounding`→`add_flag`→返回免责文案）在 (a)(b)(c) 上方向完全正确；(d) 证明纯闲聊不误伤（判定理由「通用问候语，无具体事实陈述」）。

---

## 4. 发现的问题

**无 🔴 红级 bug**（pytest / import / prompt_eval / 评测复跑 / 冒烟全部通过，验收七条无「硬未达成」）。以下为 🟡 级观察，供人决定「修 / 接受风险继续」。

### 🟡 问题 1（最重要）：「砍尾」截断会把证据末尾的关键事实切掉 → 误伤（已复现）

- **复现**（agent 亲跑）：构造证据 = 7200 字噪声日志 + 末尾一行关键事实 `北京 25°C，晴`（总长 6219 字），回答 `北京今天 25 摄氏度，晴。`（**忠于证据**）。`_truncate` 截到 6000 字后 `25°C` 被切掉（`'25°C' in truncated == False`），判定模型判 `grounded=False conf=1.0`、打 `hallucination_risk`、追加免责，reason=`无外部证据支持具体天气数据` → **误伤**。
- **根因**：`_truncate`（grounding.py L39-43）只保留**前 6000 字**，丢弃尾部；`build_evidence_text` 按「工具返回原样 + RAG 召回」顺序拼接，若关键字段在工具输出的后半段（如 `bash` 长列表、`web_search` 多条结果、日志）会被丢弃。proposal §6.3 自述「优先喂关键字段」，实现**未做**。
- **影响面**：仅当证据 >6000 字**且**关键事实落在末尾时触发；因降级是「标注不拒答」，误伤只多一条免责提示 + 一个 flag，**不阻塞正文**。但它是 v2「避免误伤」目标的一个真实边界漏洞，且 `test_truncate` 只断言「长度 ≤ 上限 + 含『已截断』」，**没有断言关键事实存活**，属测试未覆盖变更点语义。
- **建议**（供人选择，非本次必改）：① 截断改「保头保尾」（如 head 4000 + tail 2000）；② 或按 proposal §6.3 落地「关键字段优先」；③ 或提高 `EVIDENCE_MAX_CHARS`。至少给 `test_truncate` 补一条「尾随关键事实应存活」的断言。
- 附带小问题：当证据（工具+RAG）**单独**已超 6000 字时，记忆文本会在二次 `_truncate` 中被完全挤掉（merged 后又被砍回 6000）——同属「砍尾/砍头」策略问题，一并归入本条。

### 🟡 问题 2：golden「8848 vs 8848.86」标 `false` 口径偏严（指令点名，按黄处理）

- **分析**：答案 `8848 米` vs 证据 `8848.86 米`，是同一事实的取整（差 0.01%），更接近「合理约等于/合理省略」，而非「与证据矛盾（数值对不上）」。而 proposal 验收 #3 明确「合理总结/省略不被误伤」——把取整标为「幻觉」与该口径存在张力。
- **实际评测**：本轮 qwen-turbo **恰好**把它判 `false`（`pred=false` → TP，reason「8848.86 米不一致」），故 26 例机器指标全绿、无 FN。**但这依赖判定模型对「数值严格一致」的敏感度**——换模型 / 换温度 / 下次采样很可能判 `true`（视为合理约等于），届时该例翻成 FN、recall 掉点，基线不稳。
- **建议**（供人选择）：① 把该例改成**更明确的矛盾**（如证据 8848.86 → 答案 8840 或 8000），消除口径歧义；② 或把 golden 改为 `true` 并归入「合理省略」类，另补一例真数值矛盾。任选其一可让基线稳定可复现。

### 🟡 问题 3：触发放宽引入每轮一次 qwen-turbo 判定（成本/延迟，非 bug，指令要求指出）

- `GROUNDING_ENABLED` 仍是一键总开关（§1 已核），可整体关闭。
- 但默认开启时「答案非空即判」使**每轮**（含纯闲聊）都多一次 qwen-turbo 调用。冒烟 (d) 实测「你好→你好呀」确实发起了一次判定（虽判 `grounded=true` 不误伤，但这是**无意义的判定调用**）。proposal §6.1 已声明该成本、判定在流式结束后只加尾部延迟，属已接受的设计取舍。
- **建议**（供人选择）：可加「无工具 + 无 RAG + 无记忆 + 答案短/纯寒暄」快速通道跳过判定，或接受该成本（便宜模型 + 尾部延迟）。**不影响正确性**，故黄不红。

---

## 5. 最终打灯

# 🟡 黄

依据（对照 `context/rule/review.md` 写死标准）：

- **机器验证全绿**：pytest 单测 14 passed、全量 67 passed（仅 1 条 pydantic 存量告警）、import OK、prompt_eval 版本 1.2.0 全通过、真实 API 评测 26 例 F1=1.0、端到端冒烟 4/4 方向正确——均为验证 agent 亲跑，未采信 feature.md。
- **验收七条无「硬未达成」**：无红级 bug，主路径（有据也判、矛盾打标+免责、无据不回退、降级、总开关、评测基线）全部达成。
- **打黄而非绿的原因**（命中 review.md 黄灯触发项）：
  1. **变更点语义未全覆盖**：`test_truncate` 只验「长度上限 + 已截断」，未验「关键事实存活」；而 `_truncate` 砍尾在证据 >6000 字且关键事实落尾时会**真实误伤**（§4 问题 1，已复现）——proposal §6.3/§6.4 的风险点未排除。
  2. **golden 口径脆弱**：「8848 vs 8848.86」标 `false` 依赖判定模型严格程度，本轮碰巧判对，基线不稳定（§4 问题 2）。

非阻塞观察（§4 问题 3）为 proposal 已声明的成本取舍，不单独触灯。建议将 §4 问题 1/2 记入 `context/risk-ledger.md`，问题 1 优先（下次修截断策略 + 补 `test_truncate` 语义断言），问题 2 建议在评测集里消除口径歧义后再固化基线。

---

## 修复记录（2026-09-23，🟡 → 🟢）

上一轮 🟡 的两处问题已由实现者修复并复验：

1. **`_truncate` 砍尾误伤（已修）**：改为「保头 2/3 + 保尾 1/3、砍中间」；复验「关键事实落在证据末尾」场景不再误伤（`apply_grounding` 返回 None、不打标）；`test_truncate` 补尾部关键事实保留断言。
2. **「8848 vs 8848.86」golden 偏严（已修）**：改为清晰矛盾例「位于非洲」vs 证据「位于亚洲」。

机器复验：`pytest test/` 67 passed；26 例评测 P/R/F1=1.000、0 错判；prompt_eval 1.2.0 全通过。**最终打灯 🟢 绿**。

成本观察（非 bug，保留）：触发放宽后每轮多一次 qwen-turbo 判定，纯闲聊也白烧一次调用；`GROUNDING_ENABLED` 仍是一键总开关。建议回写 risk-ledger。
