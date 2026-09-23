# test_report · 20260923-111235-hallucination-gate（幻觉闸门：无据不答）

> 独立验证 agent 结论。本报告所有机器命令均由验证 agent 亲自在项目 `.venv` 下执行，未采信实现者 feature.md 的自述输出。
> 最终打灯：**🟢 绿**（见 §5）。

---

## 1. 机器验证记录（真实输出摘要）

| # | 命令 | 真实输出 | 期望 | 结果 |
|---|------|---------|------|------|
| 1 | `.venv/bin/python -m pytest test/grounding/ -q` | `11 passed in 0.30s` | 11 passed | ✅ |
| 2 | `.venv/bin/python -m pytest test/ -q` | `64 passed, 1 warning in 0.60s`（warning 为 pydantic `lifespan` 前向引用，**存量告警**，与本次变更无关） | 全绿（存量 53 + 新增 11 = 64） | ✅ |
| 3 | `.venv/bin/python -c "import backend.main; from backend.api.streaming import stream_answer, resume_answer; import backend.agent.grounding"` | `IMPORT OK` | import OK | ✅ |
| 4 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.1.0` + 四层 `[✓]` + `结果：全部通过` | 版本 1.1.0 全通过 | ✅ |

补充机器核对（命令为验证 agent 自行加验）：

| 命令/检查 | 结果 |
|---|---|
| `wc -l` 全部改动文件 | 最大 240 行（`store/db.py`，含存量），新增 `grounding.py` 160 行、`streaming/` 三件 198/143/51 行、`test_grounding.py` 112 行 → **全部 ≤300 行** ✅ |
| `PRAGMA table_info(runs)` 含 `grounding` 列 + 二次调用 `get_conn()` | `grounding: True`；二次 `get_conn()` 不报错 → **迁移幂等** ✅ |
| `_dumps(None)` / `json.loads(None or "null")` | `'null'` / `None` → **grounding=None 落库、旧行 NULL 读取均安全** ✅ |
| `GROUNDING_PROMPT.format(...)`（含 `{b}`/引号等输入） | 3 组样本均 format OK，无 KeyError；渲染后 JSON 花括号正确还原为 `{...}` → **`{{}}` 转义正确** ✅ |
| 旧 `streaming.py` 内部函数引用（`_stream_turn`/`_pending_confirm`/`_drain_pending_confirm`/`message_to_dict`） | grep 全库无残留调用；`chat.py` 的 `from backend.api.streaming import resume_answer, stream_answer` 仍成立 → **拆包无断链** ✅ |
| 触发条件 wiring（`record_tool_call`/`record_retrieved_docs`/`memory_injected`） | graph.py L302/303 记录 tool call+output，hotels.py L54 记录 retrieved_docs，graph.py L209/210 打 `memory_injected` flag → **触发信号真实可用，非臆造** ✅ |

---

## 2. 验收标准逐条核对（proposal §2 六条）

1. **[✓] 无证据事实问答被 trace 打 `hallucination_risk` flag**
   证据：`apply_grounding` 内 `collector.add_flag("hallucination_risk")`（grounding.py L158）→ `finalize()` 输出 `flags`（collector.py L215）→ `insert_run` 落 `_dumps(flags)`（runs.py L49）。`/api/runs?flag=hallucination_risk` 可查（runs.py 的 `list_runs` 用 `flags LIKE '%"hallucination_risk"%'` 匹配）。单测 `test_collector_grounding_and_flags` 断言 `hallucination_risk` 进入 `finalize()["flags"]`。

2. **[✓] 高风险回答附加「未经检索/工具验证，请谨慎采信」降级话术**
   证据：`turn.py` L124-127 在收齐 answer 后 `yield {"delta": GROUNDING_DISCLAIMER}`；免责文案 `GROUNDING_DISCLAIMER`（grounding.py L32）含「未经检索 / 工具验证，请谨慎采信」。前端 `ChatView.tsx` L356-363 对 `ev.delta` 无条件 `answer += ev.delta`，故尾部 delta 正常渲染。单测 `test_disclaimer_text` 断言文案含「谨慎采信」。

3. **[✓] 有工具/RAG/记忆支撑的回答不触发判定、零额外成本**
   证据：`should_run_grounding`（grounding.py L35-42）三条件「无工具 + 无 RAG + 无记忆」才返回 True；`apply_grounding` L140-145 据此短路。wiring 已核实（见 §1 末行）。单测 `test_should_run_grounding` 覆盖四种组合。

4. **[✓] 判定结果（verdict + confidence + 无据片段）落 trace 可回溯**
   证据：`collector.grounding` 字段 + `set_grounding`（collector.py L108/182-184）→ `finalize()` 输出 `"grounding"`（L216）→ `runs` 表加 `grounding TEXT` 列（db.py L195-199）→ `insert_run` 落 `_dumps(grounding)`（runs.py L50）→ `get_run` 读回 `json.loads(r.get("grounding") or "null")`（runs.py L177）。`/api/runs/{run_id}` 透传。单测 `test_collector_grounding_and_flags` 断言 `out["grounding"]["grounded"] is False`。

5. **[✓] 判定失败降级为「不拦截、只告警」**
   证据：`check_grounding` 对 LLM 调用 `try/except`（grounding.py L111-118）失败返回 None 并 `logger.warning`；`parse_verdict` 对空串/非 str/坏 JSON/非 bool grounded 一律返回 None（L75-89）→ 上层按 None 不拦截。单测 `test_parse_verdict_bad_input` / `test_parse_verdict_grounded_must_be_bool`。

6. **[✓] 判定解析 + 触发条件 + 降级注入 + flag 落库各有 pytest 覆盖**
   证据：`test/grounding/test_grounding.py` 共 11 条，覆盖 `parse_verdict`（6 条）、`should_run_grounding`、`should_warn`、`build_evidence_text`、collector 的 `grounding`/`has_flag`/`finalize`、免责文案。注：`check_grounding`/`apply_grounding` 涉及真实 LLM，单测有意不跑（test 文件头注释声明），改由本报告 §3 真实 API 核对补足——见 §4 观察 3。

---

## 3. 真实 API 判定方向核对结果

用 `resolve_api_key("usr-b40019392234", "bailian")` 取真实 Key（ciphertext 长度 248，解密成功），`get_platform("bailian")["base_url"]`，对 `check_grounding(query, answer, "", key, base)` 逐一实测（qwen-turbo）：

| 例 | query / answer | grounded | confidence | should_warn | 期望 | 结果 |
|----|----------------|----------|-----------|-------------|------|------|
| 1 无据事实 | 埃菲尔铁塔在哪里？/ 埃菲尔铁塔在伦敦。 | **False** | 1.0 | True | false | ✅ |
| 2 无据事实 | 珠穆朗玛峰在哪里？/ 珠穆朗玛峰在非洲。 | **False** | 1.0 | True | false | ✅ |
| 3 常识 | 1+1等于几？/ 1+1等于2。 | **True** | 1.0 | False | true | ✅ |
| 4 通用知识 | 水的化学式是什么？/ 水的化学式是H2O。 | **True** | 1.0 | False | true | ✅ |
| 5 转述用户原文 | 我叫小明，我叫什么？/ 你叫小明。 | **True** | 1.0 | False | true | ✅ |
| 6 明确拒答 | 今天天气怎么样？/ 我无法获取当前天气，这需要天气查询工具。 | **True** | 1.0 | False | true | ✅ |

判定方向 6/6 正确：无据事实判 false 且给出正确 `ungrounded_spans`（如 `['埃菲尔铁塔在伦敦']`，reason 指明真实位置在巴黎），常识/通用知识/转述用户/明确拒答均判 true 未被误伤。补充了实现者只跑 2 例之外的 4 例边界。

---

## 4. 发现的问题

**无 🔴 红级 bug。** 以下为 🟡 级以下的非阻塞观察，供人决定是否采纳：

1. **【设计边界，非 bug】本版本判定时 evidence 恒为「（无）」**
   proposal §4 点 1（evidence 含工具返回/召回/记忆）与点 2（无据才判）之间存在固有张力：触发条件保证 `check_grounding` 运行时 `tool_outputs`/`retrieved_docs` 恒空，故 `build_evidence_text` 拼出的 evidence 永远是空串 → `（无）`。这意味着「有据但答错」的误读本版本**不判**（与 proposal §1「证据内的误读属二期」一致）。`build_evidence_text` / `check_grounding` 的 `evidence` 参数是预留扩展位，当前 wiring 下是死代码路径。不影响正确性，但值得在 feature 文档显式写明「v1 判定纯靠常识，不带外部证据」。

2. **【文案/提案内部不一致，无功能影响】「前置」vs「尾部标注」**
   proposal §1 写「前置提示」，§4 点 5 写「只加尾部标注」，实现采用**尾部追加**（`"以上回答…"` 语义与追加一致）。验收标准 #2 用「附加」，实现满足。

3. **【覆盖深度，非阻塞】`apply_grounding` / `check_grounding` 无 pytest 直测**
   二者涉及真实 LLM 调用，单测有意豁免（test 文件头已声明）。`check_grounding` 的核心解析逻辑（`parse_verdict`）与 `should_warn` 已被单测覆盖，编排逻辑由本报告 §3 真实 API 6 例 + §1 import 补齐。若要更硬，建议后续给 `apply_grounding` 的「非 LLM 分支」（`GROUNDING_ENABLED=False` / collector 为 None / answer 空 / 触发条件不满足）补 mock 单测。

4. **【低风险健壮性】`apply_grounding` 整体未再包 try/except**
   `check_grounding` 内部已 try/except LLM 调用与解析，但 `GROUNDING_PROMPT.format()`（format 前）与 `get_platform()`（grounding.py L108-110、L152）在 try 之外。已实测 format 不会 KeyError（`{{}}` 转义正确）、platform 恒为 `DEFAULT_PLATFORM`，故当前不会抛。为与 proposal §2#5「只告警」对齐得更彻底，可给 `apply_grounding` 再包一层兜底。非阻塞。

5. **【安全核验通过】无 ApiKey 明文进 prompt/日志，证据不带敏感信息**
   `check_grounding` 不把 api_key 写入 GROUNDING_PROMPT（prompt 只含 evidence/query/answer）；唯一日志 `logger.warning(... e)` 打印的是异常消息（ApiKey 走 Authorization 头，错误回显不回传 key）。evidence 在本版本恒空（见观察 1），query/answer 是用户自己的会话内容发给用户自配模型，与主流程一致，无新增泄露面。DB 侧 grounding 列只存判定 JSON，无密钥。

---

## 5. 最终打灯

# 🟢 绿

依据（对照 `context/rule/review.md` 写死标准）：

- **机器验证全绿**：pytest 单测 11 passed、全量 64 passed（仅 1 条 pydantic 存量告警）、import OK、prompt_eval 版本 1.1.0 全通过——均为验证 agent 亲跑。
- **覆盖满足最低门槛**：逻辑/算法（grounding.py）有 8+ 条直接 pytest 用例且全绿；接口/路由（streaming 拆包）import/启动 OK + 全量回归过；安全/DB（迁移幂等、NULL 安全、无 key 泄露）已完成 §1 的人工审查项。
- **验收标准六条全部达成**（§2 逐一 ✓ 且附证据）。
- **真实 API 判定方向 6/6 正确**（含实现者未跑的 4 例边界）。

非阻塞观察（§4）均不触及 review.md 的黄灯触发项（无「变更点缺测试」到黄、无【推理生成】标注、proposal 风险点已在 §3 实测排除主要方向性风险）；唯一留存的「evidence 恒空」是 proposal 已声明的二期范围，非本轮缺陷。建议将 §4 观察 1/3 记入风险台账供二期排期。

---

## 六、追加部分验证（trace 呈现 + 幻觉评测）

> 独立验证 agent 对 proposal §8 追加部分（`run_stats` + `GET /api/runs/stats`、`hallucination_eval` + 评测集、`render_hallucination_report`、前端 trace 统计条 / 判定段、`test_grounding.py` 新增 2 条）的独立复核。所有命令均为验证 agent 亲跑，未采信 feature.md §六 自述。

### 6.1 机器验证记录（真实输出）

| # | 命令 | 真实输出 | 期望 | 结果 |
|---|---|---|---|---|
| 1 | `.venv/bin/python -m pytest test/grounding/ -q` | `13 passed in 0.42s` | 13 passed | ✅ |
| 2 | `.venv/bin/python -m pytest test/ -q` | `66 passed, 1 warning in 0.70s`（warning 为 pydantic `lifespan` 前向引用，**存量告警**，与本次无关） | 66 passed | ✅ |
| 3 | `cd frontend && npm run typecheck` | `tsc --noEmit` 无任何报错，exit 0 | 无报错 | ✅ |
| 4 | `cd frontend && npm run build` | `✓ 2383 modules transformed.` + `✓ built in 3.28s`（仅存量 chunk>500kB 告警 + npm 升级提示） | 成功 | ✅ |
| 5 | 幻觉评测（真实 ApiKey） | 见 §6.6，19 例复跑 | 基线可复现 | ✅ |

补充人工核对（验证 agent 自行加验）：

| 检查 | 结果 |
|---|---|
| 路由注册顺序（`import backend.main` 后打印 `/api/runs*` 路由表） | `GET /api/runs/stats` 在 `GET /api/runs/{run_id}` **之前** ✅ |
| `_dumps` 序列化分隔符 | `{"grounded": false, "confidence": 0.9, ...}`（冒号后带空格）；`["hallucination_risk"]`；`None → 'null'` ✅ |
| `render_hallucination_report` 冒烟 + HTML 转义 | `&lt;b&gt;` / `A &amp; B` / `&lt;script&gt;` 均被转义，无注入面 ✅ |

### 6.2 排查项 1：run_stats 的 SQL 正确性 → ✅ 通过

- **LIKE 与 `_dumps` 匹配**：`_dumps` 用 `json.dumps(obj, ensure_ascii=False)`，默认分隔符为 `, ` 与 `: `，故 verdict 落库为 `{"grounded": false, "confidence": 0.9, ...}`，与 `grounding LIKE '%"grounded": false%'`（冒号后确有空格）精确匹配；`flags` 落库为 `["hallucination_risk"]`，与 `flags LIKE '%"hallucination_risk"%'` 匹配。**无大小写 / 空格不匹配**。
- **三种「未判定」状态排除**：`grounding_checked` 的 WHERE 显式写 `IS NOT NULL AND != '' AND != 'null'`；`ungrounded` 的 LIKE 虽无 `IS NOT NULL` 守卫，但 SQL 中 `NULL LIKE ...` 结果为 NULL（在 WHERE 中为假），空串与字面量 `'null'` 都不含 `"grounded": false`，故三种状态均**不会**被误计入 ungrounded / flagged。
- **真实 DB 对照**：`usr-b40019392234`（33 轮，grounding 全部为 NULL×27 或 'null'×6）——`run_stats` 返回 `{total:33, grounding_checked:0, ungrounded:0, hallucination_risk:0}`，与手动 SQL 逐项一致。
- **边界用例**：临时 user 插 7 行（grounding 缺省 / 显式 None / 空串 / `'null'` / `{"grounded":true}` / `{"grounded":false}`×2，其中 1 行带 `hallucination_risk` flag）——`run_stats` 返回 `{total:7, grounding_checked:3, ungrounded:2, hallucination_risk:1}`，与期望完全一致（用完即清理）。`ungrounded(2) ≤ grounding_checked(3)` 恒成立。

### 6.3 排查项 2：路由顺序 → ✅ 通过

`runs.py` 中 `@router.get("/stats")`（L37-40）注册在 `@router.get("/{run_id}")`（L43-49）**之前**；实际路由表打印顺序为 `GET /api/runs` → `GET /api/runs/stats` → `GET /api/runs/{run_id}`。FastAPI 按注册顺序匹配，"stats" 不会被 `{run_id}` 吞掉。

### 6.4 排查项 3：eval 指标数学 → ✅ 通过

`precision=tp/(tp+fp)`、`recall=tp/(tp+fn)`、`F1=2PR/(P+R)`、`误伤率=fp/(fp+tn)`、`漏判率=fn/(fn+tp)` 公式均正确，除零均用 `if ... else 0.0` 保护。`_classify` 六分支（`pred is False` 为阳性）：
- `(False,False)=tp`、`(False,True)=fp`、`(True,True)=tn`、`(True,False)=fn`、`(None,True)=tn`、`(None,False)=fn` —— 全部正确，且与单测 `test_hallucination_eval_classify` 一致（判定失败视为「未拦截」：真有据算放行 tn、真无据算漏判 fn，用于衡量闸门拦截效果是合理口径）。

### 6.5 排查项 4：评测集 golden 标得对不对 → ✅ 全部正确

逐条人工核对 19 组：
- **7 条 golden=false 全部成立**：珠峰→非洲、埃菲尔铁塔→伦敦、首条地铁→东京（实际伦敦）、蒙娜丽莎→毕加索（实际达芬奇）、长江约 1200km（实际约 6300km）、2024 诺贝尔和平奖→「王大力」（虚构人名）、自由女神像→英国（实际法国）。
- **12 条 golden=true 全部成立**：1+1=2、H2O、地球公转一年（365 天）、一周七天、hello=你好、勾股定理（通用常识）；「我叫小明→你叫小明」等 3 条转述用户原文；3 条明确拒答。
- 任务点名复核的「自由女神像=英国」「首条地铁=东京」「2024 诺贝尔=王大力」golden=false 均正确；「地球公转一年」「勾股定理」golden=true 均正确。**无标错**。

### 6.6 排查项 6：评测运行器真实性 → ✅ 基线可复现，非编造

用 `resolve_api_key("usr-b40019392234", "bailian")` 解析真实 ApiKey（len=115，前缀 `sk-ws-`），跑 `python -m backend.eval.hallucination_eval`（19 例）：**`precision=1.000 / recall=1.000 / F1=1.000`，误伤率 0、漏判率 0（TP=7 FP=0 TN=12 FN=0）**，与 feature.md §六 声明的基线完全一致。逐条 reason 合理（如「珠峰实际在亚洲」「自由女神像是法国赠予美国」等）。

### 6.7 排查项 5：前端类型一致性 → ✅ 通过

- `GroundingVerdict`（`{grounded:boolean, confidence:number, ungrounded_spans:string[], reason:string}`）与后端 `get_run` 返回的 `grounding` verdict dict 字段一致；`RunDetail.grounding: GroundingVerdict | null` 与后端 `json.loads(r.get("grounding") or "null")` 的 dict/None 一致。
- `RunStats`（`{total, grounding_checked, ungrounded, hallucination_risk}`）与 `run_stats()` 返回四键一致。
- `RunDetail.tsx` 只引用 `grounded/confidence/ungrounded_spans/reason`，`TracesPanel.tsx` 只引用四统计键，均无未定义字段；`typecheck` 兜底通过。

### 6.8 发现的问题

**无 🔴 红级 bug。** 以下为非阻塞观察，供人决定是否采纳：

1. **【低风险健壮性】`run_stats` 的 LIKE 依赖 `json.dumps` 默认分隔符**：`'"grounded": false'` 带冒号后空格，当前与 `_dumps` 产出一致；但若未来 `_dumps` 改用 `separators=(',', ':')`（紧凑格式），此 LIKE 会静默漏计 `ungrounded`。建议在 `run_stats` 处加一行注释或改用 `json.dumps` 同款分隔符构造匹配串。当前**不影响正确性**。
2. **【评测语义，非 bug】判定失败在评测里计入 fn（真无据）/tn（真有据）**：`_classify(None, ...)` 视「判定失败」为「未拦截」。本轮 19 例零失败、未实际触发；该口径合理，但若将来把「判定失败」单独统计，能更清晰地暴露判定模型/网络的稳定性。

### 6.9 最终打灯（追加部分）

# 🟢 绿（维持）

依据（对照 `context/rule/review.md` 写死标准）：

- **机器验证全绿**：13 passed / 66 passed（仅 1 条 pydantic 存量告警）/ typecheck 无报错 / build 成功（仅存量 chunk-size 告警）——均为验证 agent 亲跑。
- **六项排查逐条通过**：SQL 正确性（含真实 DB 对照 + 7 态边界用例）、路由顺序、指标数学、golden 标注、前端类型一致、评测基线真实复现。
- **幻觉评测基线用真实 ApiKey 复跑 19 例 F1=1.0**，与 feature.md 自述一致，非编造。
- **无红级 bug**；非阻塞观察（§6.8）均不触及 review.md 黄灯触发项（变更点均有对应测试覆盖：`_classify`/`run_stats` 各有单测，前端有 typecheck + build，评测基线有真实复跑）。

综合上一轮 §5 的 🟢 绿结论，本次追加部分同样全绿，**最终打灯维持 🟢 绿**。

---

## 七、修复记录（2026-09-23，虚绿 bug 修复）

> 上一轮 §5/§6 打 🟢 绿，但用户实测发现「trace 里看不到幻觉卡片」。排查确认是一个**虚绿盲区**：触发条件把「记忆注入」当成「有证据」，而系统几乎每轮都注入记忆，导致判定被永远跳过、闸门形同虚设。

- **根因**：`should_run_grounding` 第三参 `memory_injected` 使 `memory_injected=True` 时直接跳过判定；记忆是用户画像、不支撑具体事实断言，不该作为跳过依据。
- **修复**：触发条件去掉记忆参数；`apply_grounding` 用 `_extract_memory_text()` 把注入记忆并入 evidence 喂给判定模型，避免「复述记忆」被误伤。
- **机器验证（本 agent 亲跑）**：`pytest test/grounding/` 14 passed（含 `_extract_memory_text`）；`pytest test/` 67 passed；真实 API 冒烟：无据幻觉+有记忆 → 免责提示 True ✅；复述记忆 → 免责提示 False ✅。
- **结论**：修复后闸门在「无工具 + 无 RAG」时正常触发，记忆不再阻断。最终打灯维持 **🟢 绿**。

**回写校准（按 review.md §4）**：本 bug 属「虚绿」——闸门验证时只测了判定函数正确性，未测「触发条件在实际记忆注入场景下是否真的触发」。建议把「触发条件是否被其他 flag（如 memory_injected）意外短路」纳入后续幻觉闸门类变更的必查项，回写 `context/risk-ledger.md`。
