# 独立验证报告 · 20260918-175408-memory-phase2

> 验证人：独立验证 agent（未参与编码）
> 验证时间：2026-09-18 19:08:37
> 验证对象：工作区未提交改动（`git status` 11 modified + 5 untracked），无 commit hash
> 依据：`context/rule/review.md`、`context/rule/change_sop.md` 3.3、本目录 `proposal.md` / `feature.md` / `test_plan.md`

## 结论：🔴 红

**机器可查 7 项全绿，但 proposal 第 2 节验收标准「摘要/召回/抽取任一步失败 → 降级不阻塞主流程」在召回路径上未达成（已实证复现），另有一处预算/摘要边界缺陷会把「空对话摘要」写库并注入后续每一轮。**

按 `review.md` 第一节：**「验收标准（proposal 第 2 节）有未达成项」= 红**。→ 按 `change_sop.md` 3.4，需停下问人 → 修 → 追加「修复记录」→ 回到 3.3 复验。

---

## 一、机器验证结果（test_plan 第一节，逐条亲自执行）

| # | 命令 | 真实输出摘要 | 退出码 | 通过 |
|---|------|--------------|--------|------|
| 1 | `.venv/bin/python -c "import backend.main"` | `IMPORT OK`（无异常） | 0 | ✅ |
| 2 | `.venv/bin/python -m pytest test/test_memory.py -v` | `9 passed in 0.49s`（9/9 用例名与 test_plan 一致） | 0 | ✅ |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.0.0`，身份/行为/输出格式/信息补充 4 层全 `[✓]`，`结果：全部通过` | 0 | ✅ |
| 4 | `cd frontend && npm run typecheck` | `tsc --noEmit` 无任何输出（无 TS 报错） | 0 | ✅ |
| 5 | `cd frontend && npm run build` | `✓ built in 3.14s`，产出 `dist/assets/index-MQz0n19Y.js` 等（仅既有 chunk >500kB 提示，非错误） | 0 | ✅ |
| 6 | `PRAGMA table_info(memories)` | 8 列完全符合期望：`id TEXT PK / user_id TEXT NOT NULL / session_id TEXT / kind TEXT NOT NULL / content TEXT NOT NULL / embedding TEXT / created_at REAL NOT NULL / updated_at REAL NOT NULL`；另有 `idx_memories_user_kind(user_id, kind)` 与 `sqlite_autoindex`（PK） | 0 | ✅ |
| 7 | 启动 uvicorn（127.0.0.1:8123）+ `curl /api/runs` | `HTTP/1.1 401 Unauthorized` + `{"detail":"未登录"}`（期望 200/401）；`GET /` = `200`；uvicorn 日志 `Application startup complete` | 0 | ✅ |

**补充回归**：`.venv/bin/python -m pytest -q` → `9 passed, 1 warning in 0.75s`（退出码 0）。仓库当前**只有这 9 条用例**（`test/` 下无其他被收集的测试）。

### 验证命令的环境事实
- Python 3.12.13，pytest **9.1.1**（`.venv` 内），仅装了 `anyio` 一个插件。
- `pytest` **未写入 `requirements.txt`**（全仓库 `grep -rn pytest --include=*.txt/*.toml/*.cfg/*.ini` 无声明；无 `requirements-dev.txt` / `pyproject.toml` / `setup.py`）。→ 别人按 README 装依赖后**跑不了这套测试**，复现性缺口（见风险 R6）。

---

## 二、边界与安全审查（test_plan 第二节）

| # | 检查点 | 结论 | 证据 |
|---|--------|------|------|
| 1 | 记忆按 user 隔离 | **✅ 通过** | `store/memory.py` 全部查询都带 `WHERE user_id = ?`（`load_summary`/`list_facts`/`count_facts`/`save_summary` 的 SELECT 亦带 user_id）；实测 A/B 两用户互不可见：`load_summary(B,s1)=''`、`list_facts(B)=[]`、`count_facts(B)=0`；跨会话 summary 隔离亦正确（`load_summary(A,s2)=''`）。`backend/api/` 中**无任何 memories 路由**（`grep -rn memory backend/api/` 仅命中 streaming.py 的 import），无对外越权面。 |
| 2 | 失败降级不阻塞主流程 | **❌ 未达成（部分）** | 摘要失败已实测降级：`[记忆] 摘要失败，回退为不摘要` → `info={'memory_injected': False,'summarized': False}`，不抛异常 ✅。但**召回失败会逃逸**：`recall_facts` 只把 `embed_texts` 包在 try 内，`list_facts()`（DB 读 + `json.loads`）与 `vectors[0]`（索引）、余弦计算都在 try 外；而 `context.assemble_model_messages` 第 200 行 `facts = await recall_facts(...)` **完全没有 try/except**。实测：`embed_texts` 返回 `[]` 时 → `IndexError: list index out of range` 逃逸出 `assemble_model_messages`（见下方复现）；把 `recall_facts` 直接替换成抛错函数 → 同样逃逸。该异常最终被 `api/streaming.py:193` 的兜底捕获，以 `{"error": ...}` SSE 事件推给用户——**本轮回答直接失败**，违反「不阻塞主流程、不报错」。 |
| 3 | 异步任务 fire-and-forget | **⚠️ 基本通过（1 处小瑕疵）** | 实测 `schedule_extraction` 返回耗时 **0.01 ms**（不阻塞）；`extract_facts` 内部 `except Exception` 吞掉抽取失败（实测日志 `[记忆] 事实抽取失败（忽略）`，无未捕获异常上抛）；模块级 `_background: set` 持引用防 GC，实测 0.3s 后集合回收为 0 ✅。**瑕疵**：`memory.py:171-175` 先构造协程对象 `extract_facts(...)` 再调 `asyncio.create_task`，`create_task` 抛 `RuntimeError`（无事件循环，如同步脚本）时协程已被创建却无人 await → 实测 `RuntimeWarning: coroutine 'extract_facts' was never awaited`。生产路径（`_stream_turn`）始终在事件循环内，不会命中，故仅记为黄灯小瑕疵。 |
| 4 | checkpoint 不被修改 | **✅ 通过** | `assemble_model_messages` 只在局部列表上操作（`all_messages = list(state_messages)`，`compact_history` 返回新列表）；`_chat_node` 仅 `return {"messages": [response]}`；`grep -rn "aupdate_state\|update_state\|Command(update\|put_writes" backend/agent backend/api` → 无命中。摘要只写 `memories` 表（`save_summary`），与既有 `_compact_history` 不改 checkpoint 的原则一致。 |
| 5 | 迁移幂等 | **✅ 通过** | `store/db.py` 新增 `CREATE TABLE IF NOT EXISTS memories` + `CREATE INDEX IF NOT EXISTS`，位于既有 `get_conn()` 迁移块内。实测连续 3 次 `get_conn()` 均 `OK`，`memories` 行数 0 且不报错；服务在已有该表的库上启动成功。 |
| 6 | 文件行数 | **✅ 通过（1 处笔误）** | 实测：`context.py 222`、`agent/memory.py 177`、`api/messages.py 122`、`store/memory.py 103`（新增文件均 ≤300，符合 `coding.md` §3）。`graph.py 343`（HEAD 431，**下降**）、`streaming.py 356`（HEAD 431，**下降**）——test_plan 写 357，与实测差 1（`wc -l` 换行计数差，非实质问题）。`coding.md` §3「存量超限文件本次不得再增加行数」**满足**。 |

### 复现证据（本人执行，非自述）

**缺陷 1 · 召回失败逃逸（违反验收标准 3）**
```
$ .venv/bin/python -c "... monkeypatch context.recall_facts -> raise RuntimeError ..."
RESULT: 未降级 -> 异常逃逸: RuntimeError 模拟召回崩溃(例如 embed_texts 返回空 -> IndexError)

$ # 更真实的触发：embed_texts 返回空向量列表
RESULT: 未降级 -> 异常逃逸: IndexError IndexError('list index out of range')
```

**缺陷 2 · 预算统计与「空摘要」边界（新增发现，test_plan 未覆盖）**
```
MAX_HISTORY_CHARS = 12000  SUMMARY_KEEP_TAIL = 16
memory.history_chars(带 90KB base64 图片的消息) = 90106   <-- 把 base64 全算进去了
context.messages_chars(同一条消息)               = 10     <-- 正确（图片记 1 处占位）
memory.should_summarize([带图消息])              = True   <-- 误触发预算
len(state) = 2 -> old 切片 = []                          <-- 消息数 ≤ 16 时老消息切片为空
   >> summarize_history 被调用: old_messages 条数=0, 已有摘要=''
info = {'memory_injected': True, 'summarized': True}
注入给模型的记忆段 = ['## 历史对话摘要\n【模型对空对话生成的摘要】']
```
两点问题：
1. `memory.history_chars` 用 `str(content)` 统计，**把多模态消息里的 base64 图片 data URL 全部计入**（90KB 图片 → 90106 字），而 `context.messages_chars` 用 `extract_text_content` 正确记为 10 字。**任何带图片附件的一轮都会把历史字数虚拟顶破 12000 预算。**
2. 预算触发但 `len(messages) <= SUMMARY_KEEP_TAIL(16)` 时，`old = messages[:-16] == []`，`summarize_history` 被喂进**空 transcript + 空已有摘要**，模型凭空编出摘要 → `save_summary` 落库 → 之后该会话每一轮都注入这段伪造摘要；同时 `all_messages = recent` 与原来完全相同，**预算根本没被压下来**。触发门槛很低：新会话里发一张图片（state 只有 2 条消息）即可命中。

**缺陷 3 · `parse_facts` 吞掉事实开头的数字（新增发现）**
```
'2024年搬到北京'  -> ['年搬到北京']
'3个孩子'        -> ['个孩子']
'用户在北京'      -> ['用户在北京']       (正常)
'1. 用户是工程师' -> ['用户是工程师']     (正常)
```
`memory.py:117` 的 `lstrip("-•*0123456789.、) ")` 是按字符集剥离，会把**语义上属于事实本身的数字**（年份、数量）一并删掉，写入并回注给模型的是被篡改的事实。现有用例 `test_parse_facts_strips_bullets_and_noise` 只覆盖 `"1. "` 序号场景，**未覆盖此边界**。

### 交叉核对通过的部分（正向确认）
- `assemble_model_messages` 注入结构符合 proposal §4 设计：实测 `[0] system 'SYS\n\nID'` → `[1] system kind=memory '## 相关记忆…\n\n## 历史对话摘要…'` → `[2] human`；`merge_system_messages` 发送前把相邻 system 合并为一条（kind 随合并丢失，但 trace 记录的是合并前逻辑结构，与 feature.md 偏差 4 说明一致）。
- 滚动摘要链路可用：超预算时 `info={'memory_injected': True, 'summarized': True}`，新摘要确实写入 `memories`（`load_summary` 读回一致）。
- `_evict_overflow`（pytest 未覆盖，本人补测）：`MEMORY_MAX_FACTS=3` 时插入 6 条 → 裁剪后保留最新 3 条 `['事实5','事实4','事实3']`，逻辑正确（按 `created_at DESC` 取 `[-overflow:]` 即最旧者）。
- Trace/前端链路静态核对完整：`collector.message_to_serializable` 落 `kind` → `TraceMessage.kind?`（types.ts）→ `RunDetail.tsx` 用 `{msg.kind ?? msg.type}` + `.trace-msg-type.memory` 配色 → `TracesPanel` 的 `FLAG_LABELS`/`FLAG_OPTIONS` 均加 `memory_injected`；后端 `GET /api/runs?flag=` 走 `store.list_runs` 的 `r.flags LIKE ?`，`collector.add_flag("memory_injected")` 落在 `flags` JSON 内，**筛选链路静态自洽**。
- 无新增第三方依赖：`git diff requirements.txt package.json` 为空；记忆向量化复用既有 `rag/embeddings.py`，召回用 numpy 暴力余弦（符合 proposal「不引入独立向量库」）。

---

## 三、验收标准对照（proposal 第 2 节）

| 验收项 | 状态 | 依据 / 原因 |
|--------|------|-------------|
| 长对话超预算时模型仍能答出早期关键信息 | **无法验证（且存疑）** | 需真实 ApiKey + 真实长对话，属 proposal §7 人工判断项。另：缺陷 2 表明预算统计在带图/单条长文本时会误触发且摘要输入可能为空，摘要可信度打折。 |
| 说过偏好后（含新会话）能被召回并影响回答 | **部分验证 / 待人工** | 召回链路机器可验部分已证：单测 `test_recall_ranks_by_cosine_and_filters_low_similarity` 排序+阈值通过；本人补测证明召回结果会以 `kind=memory` 段确实进入模型输入。「是否真的改变回答」需真实 ApiKey，人工。 |
| 摘要/召回/抽取任一步失败 → 降级不阻塞、不报错 | **❌ 未达成** | 摘要有 try ✅、抽取有 try ✅、召回**只有 embed 失败被吞**；`embed_texts` 返回空/短向量 → `IndexError` 逃逸出 `assemble_model_messages` → 用户收到 `{"error": ...}`，本轮无回答。已在第一节/复现证据给出真实输出。 |
| checkpoint 原始历史不被修改 | **✅ 达成** | 代码审查 + 无任何 state 写入调用；摘要落 `memories` 表。 |
| `memories` 表迁移幂等、旧库启动自动建表 | **✅ 达成** | 机器验证 #6 + 3 次 `get_conn()` 实测 + 服务启动成功。 |
| 记忆逻辑至少 1 条 pytest（召回排序/预算判断/摘要回退之一） | **✅ 达成** | 9 passed，其中 `test_recall_ranks_by_cosine_and_filters_low_similarity`（召回排序）、`test_should_summarize_respects_budget`（预算判断）均命中。 |
| 注入记忆在 Trace 里以独立 `memory` tag 展示 | **链路达成 / 渲染无法自动验证** | 后端 `kind` 落库链路已通并核对；前端 tag 渲染需真实产生一次记忆注入后目视（无法自动验证）。 |
| 注入轮次自动打 `memory_injected` flag 且可在面板筛选 | **链路达成 / 端到端无法自动验证** | `add_flag` → `flags` 落库 → `/api/runs?flag=` LIKE 过滤 → 前端下拉项，四段静态核对一致；实际筛选效果需真实数据目视。 |

**feature.md 偏差核对**：`git diff --stat` 实测 `11 files changed, 127 insertions(+), 218 deletions(-)`，与 feature.md 完全一致；`graph.py 431→343`、`streaming.py 431→356` 亦一致（357 为笔误）。偏差 1/2（新增 `agent/context.py`、`api/messages.py`）理由成立且符合 `coding.md` §3；偏差 3（pytest 未入 requirements）已核实并计为风险 R6；偏差 4（未实测多条 system，直接采用合并方案）**属 proposal 风险 7 未排除**，需人工追认。

---

## 四、风险清单

| ID | 风险 | 级别 | 说明 / 影响面 |
|----|------|------|----------------|
| R1 | **召回失败不降级**（验收标准 3 未达成） | 🔴 阻塞 | `context.py:200` 无 try 包裹；`recall_facts` 仅保护 `embed_texts`。触发条件：embedding 返回条数少于输入、DB 读/`json.loads` 异常。影响：本轮回答以 `error` 事件失败。修复量约 3 行（把 `await recall_facts(...)` 包进 try/except 返回 `[]`，并给 `recall_facts` 整体兜底）。 |
| R2 | **预算统计把 base64 图片计入 → 误触发摘要** | 🔴 阻塞（同批修） | `memory.history_chars` 用 `str(content)`；`context.messages_chars` 已用 `extract_text_content`，两者不一致。任何带图轮次都会顶破 12000 预算。 |
| R3 | **空 transcript 生成并持久化伪造摘要** | 🔴 阻塞（同批修） | `len(messages) <= SUMMARY_KEEP_TAIL` 时 `old=[]` 仍调模型 → 伪造摘要写库并注入该会话后续每一轮，且预算未被压缩。修复：`len(all_messages) > SUMMARY_KEEP_TAIL` 才摘要。 |
| R4 | `parse_facts` 剥离事实开头数字，篡改记忆内容 | 🟡 | 如 `2024年搬到北京 → 年搬到北京`；无对应用例。影响：召回注入被篡改的事实。 |
| R5 | `【推理生成】` 标注存在于 `context.py:135`（`merge_system_messages`） | 🟡 | 按 `review.md` 第一节「代码里出现【推理生成】标注」= 黄灯；`coding.md` §5 亦要求纳入黄灯检查项。且 proposal 风险 7「多条 system 是否被 DashScope 支持」**未实测即改用合并方案**（feature.md 偏差 4 自述「无明文 ApiKey 无法实测」）→ 该风险本轮**未排除**。 |
| R6 | `pytest` 已装 `.venv` 但**未写入 `requirements.txt`**，仓库无 dev 依赖文件 | 🟡 | 新人/CI 按 `requirements.txt` 装完跑不了 `test_memory.py`；绿灯门槛「逻辑/算法需 ≥1 条 pytest」在他人环境下不可复现。待人工决定是否固化（建议加 `requirements-dev.txt` 或注释行）。 |
| R7 | 核心变更点缺对应测试 | 🟡 | 9 条用例覆盖 `should_summarize`/`parse_facts`/`build_memory_text`/`merge_system_messages`/`compact_history`/store 读写/召回排序，但 **`assemble_model_messages`（注入编排主入口）、`extract_facts`、`schedule_extraction`、`_evict_overflow`、graph/streaming 集成全部无用例**。按 `review.md` 绿灯门槛「变更点若无对应测试，最高只能打黄」。 |
| R8 | 同步创建协程后 `create_task` 失败 → `RuntimeWarning: never awaited` | 🟡 | 仅同步上下文命中；生产路径不触发。 |
| R9 | 客户端中途断开 → `_stream_turn` 生成器在 `yield` 处被关闭，尾部 trace 落库与 `schedule_extraction` 均被跳过 | 🟡（既有） | trace 落库原本就有此特性，本次让长记忆抽取同样受影响；非本次引入，但记忆覆盖率会因此不可预期。 |
| R10 | 长记忆明文落库、跨会话、用户无自助删除入口 | 🟡（待决策） | 事实含用户画像（身份/城市/技术栈）明文存 `memories`，与既有 sessions 明文同等级，未新增泄露面；但**无任何 API/前端入口让用户查看或删除长期记忆**，`delete_fact` 仅内部裁剪调用。属产品/合规决策项。 |
| R11 | `MEMORY_MIN_SIM = 0.35` 自述「保守默认，待真实数据校准」 | 🟡 | `coding.md`/`review.md` 对「agent 自述不确定」一律黄灯；召回阈值未经真实数据校准。 |
| R12 | AGENTS.md 自动生成区未刷新 | ⚪ 提示 | §8 文件清单/§3 模块职责未含 `agent/context.py`、`agent/memory.py`、`api/messages.py`、`store/memory.py`；按 §7 由 pre-commit 钩子刷新，提交前会自动补上（本次改动尚未 commit）。 |

### proposal 第 6 节风险点逐条核对

| proposal 风险 | 是否排除 | 结论 |
|----------------|----------|------|
| 1 摘要质量（qwen-turbo 可能丢信息） | ❌ 未排除 | 需人工；且 R2/R3 让摘要质量在带图/短消息场景进一步不可信。 |
| 2 摘要同步生成增加延迟 | ⚠️ 部分 | 代码为**同步 await**（`context.py:187`），确有延迟；缓解项「异步预热」未实现，proposal 自述为后续优化 → 接受现状需人工确认。 |
| 3 异步抽取并发/失败边界未充分验证 | ⚠️ 已补验 | 本人补测：失败被吞、不阻塞（0.01ms）、引用集合回收正常、无未捕获异常 → 基本排除，仅留 R8 小瑕疵。 |
| 4 每轮 embedding 成本上升 | ❌ 未排除 | 第一版无采样，proposal 明示「需观察」。 |
| 5 记忆膨胀 | ⚠️ 部分 | 上限 + 相似去重已实现（`_evict_overflow` 补测正确、`FACT_DEDUP_SIM=0.92`）；阈值 0.92 未经真实数据校准。 |
| 6 新逻辑缺自动化测试 | ⚠️ 部分 | 已有 9 条；但核心编排/抽取/调度仍无用例（R7）。 |
| 7 多条 system 兼容性未经实测 | ❌ 未排除 | 未实测，改为「发送前合并 + trace 记录逻辑结构」的取舍，**需人工追认**（R5）。 |

---

## 五、需人工决定的事项

1. **【阻塞·必须先修】R1+R2+R3 三处缺陷**：建议一并修复后回到 3.3 复验——
   a) `context.assemble_model_messages` 把 `await recall_facts(...)` 包入 try/except 降级为 `[]`（并在 `recall_facts` 内对 `list_facts`/索引整体兜底）；
   b) `memory.history_chars` 改用 `context.extract_text_content`（或对多模态块只计文本）统计，与 `messages_chars` 口径统一；
   c) 仅当 `len(all_messages) > SUMMARY_KEEP_TAIL` 时才触发摘要，否则跳过（避免空 transcript 伪造摘要并落库）。
   若判定 R1 的触发路径（embedding 返回空/短向量、DB 读异常）在实践中不可达，可将其降级为黄灯「接受风险继续」——但**验收标准第 3 条的字面要求当前不成立**，需人明确书面接受。
2. **R5 取舍追认**：proposal 要求「先实测多条 system 支持性，不支持再回退」，实际因无 ApiKey 未实测即采用合并方案。trace 记录合并前结构、模型收到合并后单条 system，是否接受？（若接受，建议同时更新 proposal 风险 7 状态。）
3. **R6 pytest 依赖归属**：是否新增 `requirements-dev.txt`（或 `requirements.txt` 内注释）固化 `pytest`？当前状态他人无法复现测试。
4. **R7 补测范围**：是否要求为 `assemble_model_messages`（含记忆注入与降级）、`extract_facts`、`schedule_extraction` 补最小用例？否则按绿灯门槛本变更永远无法达标。
5. **R2 修复后需人工复跑**：带图片附件的会话是否不再产生「凭空摘要」；以及长对话摘要质量、偏好召回是否真的改变回答（需真实 ApiKey 的手工验证，`test_plan.md` 第四节已列为人工项，本轮**未做**，故对应验收标准记为「无法验证」而非「达成」）。
6. **R10 长期记忆的可见/可删入口**：是否需要给用户提供查看/删除长期记忆的功能（当前无任何入口）。

---

## 附：本次验证执行过的命令清单（可复核）

```
git status --short / git diff --stat / git log --oneline -3
.venv/bin/python -c "import backend.main"
.venv/bin/python -m pytest test/test_memory.py -v
.venv/bin/python -m pytest -q
.venv/bin/python -m backend.eval.prompt_eval
cd frontend && npm run typecheck
cd frontend && npm run build
.venv/bin/python -c "PRAGMA table_info(memories) / sqlite_master"
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8123  +  curl -i /api/runs, curl /  (验证后已 kill)
.venv/bin/python -c "get_conn() x3 幂等"
.venv/bin/python -c "store 层 user 隔离实测"
.venv/bin/python -c "_evict_overflow 上限裁剪实测"
.venv/bin/python -c "schedule_extraction 无循环/抽取失败/不阻塞实测"
.venv/bin/python -c "assemble_model_messages 注入结构 + 摘要链路 + 摘要失败降级实测"
.venv/bin/python -c "history_chars 多模态统计 + 空 transcript 摘要实测"
.venv/bin/python -c "parse_facts 数字开头边界实测"
grep -rn "delete_fact|aupdate_state|update_state|Command(update|put_writes|memory" backend/ test/
grep -rn pytest --include=*.txt/*.toml/*.cfg/*.ini
wc -l + git show HEAD:<file> | wc -l  （行数对比）
```

> 未修改任何产品代码；本报告是本次验证唯一写入的文件。

---

# 修复记录（修复轮次 1）

> 修复人：写代码 agent
> 修复时间：2026-09-18（首轮验证后）
> 触发：本报告判定 🔴 红（R1/R2/R3 阻塞 + R4 黄），人工裁决「选 1 修」

## 修复内容

| 风险 | 修复动作 | 落点 |
|------|----------|------|
| **R1** 召回失败逃逸 | ① `recall_facts` 整段包 try（含 `list_facts`/索引/余弦），向量为空时 `return []`；② `context.assemble_model_messages` 的 `await recall_facts(...)` 再兜一层 try/except，双保险 | `backend/agent/memory.py`、`backend/agent/context.py` |
| **R2** 预算把 base64 计入 | `message_text` 改为按多模态块取文本、图片块记 `[图片]` 占位，与 `context.messages_chars` 口径统一 | `backend/agent/memory.py` |
| **R3** 空 transcript 伪造摘要 | 摘要触发条件加 `len(all_messages) > SUMMARY_KEEP_TAIL`，条数不足时跳过 | `backend/agent/context.py` |
| **R4** `parse_facts` 篡改数字 | 改用正则 `_FACT_PREFIX_RE` 只剥行首列表标记（`- ` / `* ` / `1. ` / `2) `），不再用字符集 `lstrip` | `backend/agent/memory.py` |
| **R8** 未 await 协程警告 | `schedule_extraction` 先 `get_running_loop()` 取 loop，再 `loop.create_task(...)`，无循环时根本不创建协程 | `backend/agent/memory.py` |

## 新增回归用例（对应 R1–R4）

`test/test_memory.py` 由 9 条增至 **14 条**，新增：
- `test_message_text_ignores_image_base64`（R2）
- `test_parse_facts_keeps_leading_digits`（R4）
- `test_recall_returns_empty_when_embedding_empty`（R1）
- `test_recall_swallows_store_errors`（R1，DB 抛错路径）
- `test_assemble_skips_summary_when_no_old_messages`（R3，同时覆盖 `assemble_model_messages` 主入口，部分回应 R7）

## 修复后自测（写代码 agent 执行）

```
.venv/bin/python -c "import backend.main"      -> OK
.venv/bin/python -m pytest test/test_memory.py -> 14 passed
.venv/bin/python -m backend.eval.prompt_eval   -> 全部通过
```

## 本轮未处理的（仍需人工决定，见本报告第五节）

- **R5**：`【推理生成】` 标注 + proposal 风险 7「多条 system」取舍，待人工追认；
- **R6**：pytest 未写入依赖文件，待人工决定是否固化；
- **R7**：`extract_facts` / `schedule_extraction` / `_evict_overflow` / graph-streaming 集成仍无用例；
- **R9–R12**：断连丢失尾部、长期记忆无自助删除入口、召回阈值未校准、AGENTS.md 待刷新。

## 状态

已按 SOP 3.4 回到 **3.3 复验**：请独立验证 agent 对本轮修复重新验证并更新结论。

---

# 复验结论（轮次 2）

> 复验人：独立验证 agent（未参与编码，未修改任何产品代码）
> 复验时间：2026-09-18 20:08:42
> 复验对象：修复轮次 1 后的工作区（`git status` 11 modified + 5 untracked，无 commit hash）
> 依据：`context/rule/review.md`、`context/rule/coding.md`、本目录 `proposal.md` / `feature.md` / `test_plan.md` + 本报告「修复记录（修复轮次 1）」
> 方法：逐条重跑机器验证；对 R1–R4/R8 自己写最小脚本做**对抗性证伪**（含突变式反证：把旧实现还原，确认新用例在旧代码下会失败）；`-W error::RuntimeWarning` 严格模式。

## 结论：🟡 黄

**上一轮判红的三项阻塞缺陷（R1 召回失败逃逸、R2 base64 顶破预算、R3 伪造空摘要落库）已全部确认修复；R4/R8 亦确认修复；未发现修复引入的回归；机器可查 7 项全绿（实际 14 passed）。** 但按 `review.md` 第一节，`【推理生成】` 标注与「待真实数据校准」自述不确定仍在 → 黄灯；另有 R5/R6/R7/R10/R11 等待人工决定项与本轮新发现的 6 条低危问题（N1–N6）。

- **不再阻塞**：上轮 5 条「需人工决定」中的第 1 条（R1+R2+R3）已由修复轮次 1 关闭并经本轮独立复现证实。
- **若人工书面追认 R5**（多条 system 实测取舍）**并接受 R6/R7/R10/R11 现状**，则该变更处于「机器全绿 + 阻塞项清零」状态，可按绿灯收尾；本报告不代替人做该追认，故不自行打绿。

## 一、机器验证复跑（test_plan 第一节 7 条，本人逐条执行，非引用自述）

| # | 命令 | 真实输出摘要 | 退出码 | 通过 |
|---|------|--------------|--------|------|
| 1 | `.venv/bin/python -c "import backend.main"` | `IMPORT OK` | 0 | ✅ |
| 2 | `.venv/bin/python -m pytest test/test_memory.py -v` | **`14 passed in 0.54s`**（14 条用例名逐一列出，含新增 5 条） | 0 | ✅（plan 写「9 passed」已**过时**，见 N3） |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.0.0`，身份/行为/输出格式/信息补充 4 层全 `[✓]`，`结果：全部通过` | 0 | ✅ |
| 4 | `cd frontend && npm run typecheck` | `tsc --noEmit` 零输出 | 0 | ✅ |
| 5 | `cd frontend && npm run build` | `✓ built in 3.22s`，产出 `dist/assets/index-MQz0n19Y.js` 等（仅既有 chunk >500kB 提示） | 0 | ✅ |
| 6 | `PRAGMA table_info(memories)` | 8 列完全一致：`id TEXT PK / user_id TEXT NOT NULL / session_id TEXT / kind TEXT NOT NULL / content TEXT NOT NULL / embedding TEXT / created_at REAL NOT NULL / updated_at REAL NOT NULL`；索引 `idx_memories_user_kind(user_id, kind)` + `sqlite_autoindex_memories_1` | 0 | ✅ |
| 7 | uvicorn 127.0.0.1:8124 + `curl /api/runs` | `HTTP/1.1 401 Unauthorized`；`GET /` = `200`；日志 `Application startup complete`（验后已 kill） | 0 | ✅ |

**补充回归**：`.venv/bin/python -m pytest -q` → `14 passed, 1 warning in 0.55s`（退出码 0；唯一 warning 来自第三方 `pydantic_settings`，与本变更无关）。仓库仍只有这 14 条被收集用例。

## 二、R1–R4/R8 修复的对抗性验证（自己写脚本，不依赖仓库用例）

### R1 · 召回失败逃逸 → **确认修复 ✅**

| 施加的故障 | `recall_facts` 结果 | `assemble_model_messages` 结果 | 判定 |
|-----------|--------------------|-------------------------------|------|
| `list_facts` 抛 `RuntimeError("db down")` | `[]`（日志 `[记忆] 召回失败，跳过记忆注入: db down`） | `{'ok': True, 'n': 2, 'info': {'memory_injected': False, 'summarized': False}}` | ✅ 降级 |
| `embed_texts` 返回 `[]` | `[]`（日志 `召回向量为空`） | 同上，正常组装 | ✅ 降级 |
| `embed_texts` 返回少于输入的向量（1→0） | `[]` | 正常 | ✅ 降级 |
| DB 内 `embedding` 内容损坏（`"not-a-vector"`） | `[]`（`could not convert string to float`） | 正常 | ✅ 降级 |
| 直接把 `context.recall_facts` 替换成抛错函数 | — | `ok=True, n=2`（`召回异常，跳过记忆注入`） | ✅ 二层兜底生效 |
| `summarize_history` 抛错 | — | `ok=True, n=21`（`摘要失败，回退为不摘要`） | ✅ 降级 |
| `list_facts` + `summarize_history` 同时抛错 | `[]` | `ok=True, n=21` | ✅ 降级 |
| **真实网络路径**：真实 `embed_texts` + 假 key | `[]`（`向量化失败: code=InvalidApiKey`） | 正常 | ✅ 真实降级 |

**「真出异常时本轮仍能正常组装出 messages」**：以模仿 `streaming.py:193` 的驱动（异常即产出 `{"error": ...}`）包裹 `assemble_model_messages`，上表 8 种故障**全部返回 messages，未产出任何 error 事件**。另发现 `recall_facts` 自身的 try **起点之前**仍有一行可抛代码（`query.strip()`，见 `memory.py:105`）：实测 `recall_facts(uid, None, "k")` 抛 `AttributeError: 'NoneType' object has no attribute 'strip'`，但被 `context.py:204-207` 的新兜底接住（`assemble(query=None)` 正常返回 2 条消息）。**结论：R1 在「本轮回答不被打断」这一验收边界上闭合**；内层 guard 不完整但外层补上（记为 N2，覆盖缺口）。

### R2 · 预算计入 base64 → **确认修复 ✅**

```
90KB base64 图片消息:
  memory.history_chars = 10        （上轮 = 90106）
  context.messages_chars = 10
  should_summarize = False         （上轮 = True，误触发）
```
口径一致性 parity（`memory.history_chars` vs `context.messages_chars`，8 种消息形态）：纯文本 200/200、多模态 10/10、`image_url` 为字符串 6/6、多图 9/9、空内容 0/0、AI+Tool 120/120、非 dict 块 11/11、未知块类型 5028/5028 —— **全部一致**。走完整 `assemble_model_messages`（带 90KB 图）时 `summarize_history` 调用 0 次、`save_summary` 调用 0 次。反向验证（防止「把预算关掉」式假修复）：13000 字纯文本 `should_summarize = True`，预算仍生效。

### R3 · 空 transcript 伪造摘要 → **确认修复 ✅**

| 场景 | `should_summarize` | `summarize_history` 调用 | 落库 | info |
|------|-------------------|--------------------------|------|------|
| n=16 条 ×1000 字（16000 字超预算，恰好 == `SUMMARY_KEEP_TAIL`） | True | **0** | 0 行 | `summarized=False` |
| n=17 条（old 切片 1 条） | True | 1（old=1） | 1 行 summary | `summarized=True` |
| n=20 条（old 切片 4 条） | True | 1（old=4） | 1 行 | `summarized=True` |
| n=2 条（2000 字，未超预算） | False | 0 | 0 行 | — |

滚动链路仍可用（反向验证，未把功能改死）：n=20 生成摘要真实落库 `('summary','摘要v1(已含4条老消息)')` → 次轮（短对话）`info.memory_injected=True` 且注入内容 `'## 历史对话摘要\n摘要v1(已含4条老消息)'` → **再下一轮 13000 字单条消息（超预算但条数不足）`summarize_history` 调用 0 次、落库仍 1 行未被覆盖** → 新会话 `session_id=sess-other` 不串摘要（`memory_injected=False`）。**关键点：修复没有用「关闭摘要」蒙混，超窗口（n=17/20）时摘要照常触发。**

### R4 · `parse_facts` 吞掉事实开头数字 → **要求场景确认修复 ✅；另有同类残留（N1）**

```
'2024年搬到北京'  -> ['2024年搬到北京']   ✅ 原样（上轮 '年搬到北京'）
'3个孩子'        -> ['3个孩子']         ✅ 原样（上轮 '个孩子'）
'- 正常条目'      -> ['正常条目']         ✅ 剥标记
'1. 带序号'       -> ['带序号']           ✅ 剥标记
旧噪声用例含 '1. 用户在北京' / '- 喜欢简洁回答' / '*   ' / '2) ...'（>200 字丢弃）-> ['用户在北京','喜欢简洁回答']  ✅
```
**对抗性残留（同族缺陷，见 N1）**：`'3.14是圆周率' -> ['14是圆周率']`、`'-5度以下偏好' -> ['5度以下偏好']`、`'2、3线城市' -> ['3线城市']`、`'1.2.3 版本' -> ['2.3 版本']` —— 正则 `^\s*(?:[-•*]+|\d+[.、)])\s*` 仍会把「小数点/负号开头的正文」当列表标记。抽取提示词已写「每行输出一条，不加序号」，实际触发概率低，故不阻塞。

### R8 · 同步上下文未 await 警告 → **确认修复 ✅**

```
$ .venv/bin/python -W error::RuntimeWarning  # 同步上下文调用 schedule_extraction
schedule_extraction 返回正常；extract_facts 调用次数 = 0
未 await 的 extract_facts 协程对象数 = 0        （gc 全量扫描，上轮为 1）
后台任务集合 = set()
R8-1 OK（无 RuntimeWarning，无未 await 协程），退出码 0
```
反向验证（功能未破坏）：事件循环内调用 → `_background` 置 1 → `extract_facts` 实际执行 1 次 → 执行后集合回收为 0；空 `answer` / 空 `api_key` 早退分支不再增发调用、不抛错。

### 新增 5 条回归用例的「突变式反证」（确认不是同义反复）

把修复前旧实现还原后跑同一断言：

| 新增用例 | 旧实现下的结果 | 判定 |
|---------|---------------|------|
| `test_message_text_ignores_image_base64`（R2） | 旧 `str(content)` 口径 = **5106** 字（>50，断言 `<50` 失败） | ✅ 真回归 |
| `test_parse_facts_keeps_leading_digits`（R4） | 旧 `lstrip` = `['年搬到北京','个孩子的父亲','喜欢简洁回答']`（断言 `'2024年搬到北京' in facts` 失败） | ✅ 真回归 |
| `test_recall_returns_empty_when_embedding_empty`（R1） | 旧代码 `vectors[0]` 在 try 之外 → `IndexError: list index out of range` | ✅ 真回归 |
| `test_recall_swallows_store_errors`（R1） | 旧代码 `list_facts()` 在 try 之外 → 异常逃逸 | ✅ 真回归 |
| `test_assemble_skips_summary_when_no_old_messages`（R3） | 旧代码无条件调摘要 → `calls==1`，断言 `==0` 失败 | ✅ 真回归 |

**5 条用例均非 happy-path 同义反复，且断言方向正确（不是「不抛错即通过」）。** 覆盖不足处：R1 在 `context.py` 层新增的 try/except（204-207）**无任何用例触及**（见 N2）；R3 未覆盖 n=16/17 边界（本人补测已过）；R4 未覆盖小数/负号边界（见 N1）。

## 三、回归检查（修复是否破坏别处）

| 检查项 | 结论 | 证据 |
|--------|------|------|
| `message_text` 改动破坏 `summarize_history` 的 transcript？ | **未破坏 ✅** | 伪造 LLM 抓 prompt：50 连 `'A'` 不再出现、`[图片]` 占位存在、旧摘要仍在、长文本仍精确截断到 400 字（400 在、401 不在） |
| `history_chars` 既有语义被改？ | **仅多模态一项改变（=修复目标）✅** | 纯文本 旧=300/新=300 不变；多模态 旧=90105/新=9（预期变化） |
| `message_text` 被别处依赖？ | **引用面已核对 ✅** | 仅 `memory.history_chars` / `summarize_history` / `extract_facts` / `context.merge_system_messages` / `context` 日志 5 处，语义均按「纯文本」使用 |
| 拆出的 `message_to_dict` 是否改了旧接口行为？ | **未改 ✅** | `streaming.py` 与 `api/messages.py` 两版逐行等价（仅移动），`api/routers/sessions.py` 改 import 路径；`GET /api/sessions/{id}/messages` 路由未变 |
| `merge_system_messages` 引入新行为风险？ | **文本等价，可接受 ⚠️（R5 范畴）** | 发送前把相邻 system 合并为一条（含附件 SystemMessage 被并入首条 system），文本拼接顺序不变、语义等价；`trace` 与 `log_llm_input` 记录的是**合并前**逻辑结构，故 `memory` tag 仍可展示（与 feature.md 偏差 4 一致） |
| 行数合规（coding.md §3） | **合规 ✅** | `memory.py 215`、`context.py 229`、`messages.py 122`、`store/memory.py 103`（新增文件均 ≤300，但 memory/context 本轮分别 +38/+7，见 N3）；`graph.py 343`（HEAD 431，**下降**）、`streaming.py 356`（HEAD 431，**下降**） |
| 新依赖 / 新路由 / 表结构破坏 | **无 ✅** | `git diff requirements.txt frontend/package.json` 为空；`backend/api/routers/` 无任何 memory 引用（无新对外越权面）；`memories` 表 3 次 `get_conn()` 幂等（行数稳定为 1，见 N4），旧库启动成功 |
| 用户隔离 / 召回隔离 | **仍正确 ✅** | 复跑：`load_summary(B,'s1')=''`、`list_facts(B)=[]`、`count_facts(B)=0`、跨会话 `load_summary(A,'s2')=''`；`recall(A)=['A的事实']` 而 `recall(B)=[]` |
| `_evict_overflow` 上限裁剪（R7 未覆盖项补测） | **仍正确 ✅** | `MEMORY_MAX_FACTS=3` 插入 6 条 → 保留最新 `['事实5','事实4','事实3']` |
| checkpoint 未被写 | **仍成立 ✅** | 修复只改了 `memory.py` / `context.py` 的局部逻辑，未新增任何 `update_state`/`put_writes`；摘要仍只落 `memories` 表 |

## 四、本轮新发现的问题（N1–N6，均为低危，不阻塞）

| ID | 问题 | 级别 | 证据 / 影响 |
|----|------|------|-------------|
| **N1** | `parse_facts` 正则仍会剥掉「小数点/负号开头」的正文 | 🟡 | `'3.14是圆周率'→'14是圆周率'`、`'-5度以下偏好'→'5度以下偏好'`、`'2、3线城市'→'3线城市'`、`'1.2.3 版本'→'2.3 版本'`。与 R4 同族；抽取提示词已要求「不加序号」，实际触发概率低。若要彻底修：仅在行首为 `\d+[.)、]\s`（要求序号后必须有空白）或 `[-*•]\s` 时才剥 |
| **N2** | R1 的第二层兜底（`context.py:204-207`）**无测试覆盖**；内层 `recall_facts` 的 guard 起点前仍有可抛代码 | 🟡 | 实测 `recall_facts(uid, None, "k")` 抛 `AttributeError`；`assemble(query=None)` 靠外层兜底才没崩。而生产路径 `query` 恒为 `extract_text_content(...)` 的字符串（经查 `graph.py:198`），故当前不可达 → 属「防御代码未被验证」而非缺陷 |
| **N3** | `test_plan.md` 未随修复轮次更新 | 🟡 | §一 #2 仍写「期望 9 passed」（实测 14）；§二 #6 行数仍写 `context.py 222 / memory.py 177`（实测 229 / 215）。命令本身全绿，仅文档漂移（均仍 ≤300，不影响 coding.md §3 合规性） |
| **N4** | 上轮复现缺陷 2 时把伪造摘要**写进了真实开发库**且未清理 | 🟡 | 实测开发库残留 1 行：`memories(user_id='no-such-user', session_id='no-such-sess', kind='summary', content='【模型对空对话生成的摘要】')`。修复只阻止新产生、未清理旧行；因 `user_id` 非真实用户，无功能影响，建议手工 `DELETE` |
| **N5** | `SUMMARY_KEEP_TAIL`（memory.py=16）与 `context.KEEP_TAIL`（context.py=16）是两份独立常量，仅靠注释「对齐」 | 🟡（可维护性） | 任一处单独修改会导致「摘要保留窗口」与「工具原文压缩窗口」错位；建议 context 直接 `from backend.agent.memory import SUMMARY_KEEP_TAIL` |
| **N6** | 预算在「条数少但单条极长」时不生效 | 🟡（设计取舍） | 实测 1 条 13000 字消息：`should_summarize=True` 但（R3 保护好）不摘要 → 原文 13000 字全量送模型，`12000` 并非硬上限。这是 R3 修复的**有意代价**（优于伪造摘要），且与 Phase 2 之前行为一致，但需人工知悉：验收标准 1「超预算靠摘要兜住」在「少条数超长」场景不成立 |

## 五、R1–R4/R8 修复确认表（汇总）

| 缺陷 | 上轮级别 | 本轮判定 | 依据 |
|------|---------|---------|------|
| R1 召回失败逃逸（验收标准 3 未达成） | 🔴 阻塞 | **✅ 确认修复** | 8 种故障注入全部降级为 `[]`/不注入，`assemble_model_messages` 始终返回 messages、不产 error 事件；二层兜底生效 |
| R2 base64 计入预算 | 🔴 阻塞 | **✅ 确认修复** | 90KB 图 → 10 字（原 90106）、8 种形态口径全一致、不再误触发摘要 |
| R3 空 transcript 伪造摘要落库 | 🔴 阻塞 | **✅ 确认修复** | n=16 超预算 0 次摘要 0 行落库；n=17/20 摘要照常触发；已有摘要不被伪造覆盖；会话隔离正确 |
| R4 `parse_facts` 篡改数字 | 🟡 | **✅ 要求场景修复**（残留 N1） | 4 个指定输入全部正确；旧实现突变反证失败 |
| R8 `never awaited` 警告 | 🟡 | **✅ 确认修复** | `-W error::RuntimeWarning` 下无警告、无未 await 协程对象；循环内功能正常 |

## 六、残留风险与待人工决定项（更新上一轮第五节）

| 原编号 | 状态 | 说明 |
|--------|------|------|
| 1（R1+R2+R3 阻塞） | **✅ 已关闭** | 本轮独立复现确认修复，无需再审 |
| 2（R5 `【推理生成】` + proposal 风险 7 多条 system 未实测） | **仍在，待人工追认** | `context.py:135` 标注仍在；合并方案未实测 DashScope 多条 system 支持性。这是本轮判黄的首要原因 |
| 3（R6 pytest 未写入依赖文件） | **仍在，待人工决定** | `requirements.txt` diff 为 0；他人按 README 装依赖后跑不了这 14 条用例 |
| 4（R7 补测范围） | **部分改善，仍在** | 新增 5 条含 `assemble_model_messages` 主入口 1 条；但 `extract_facts`、`schedule_extraction`、graph/streaming 集成、`_evict_overflow`、`context` 层降级兜底仍无用例 |
| 5（R2 修复后人工复跑 + 长对话/偏好召回真实效果） | **仍待人工（需真实 ApiKey）** | 本轮**未做**，`test_plan.md` 第四节三项人工项仍为「无法验证」（不记为「达成」） |
| 6（R10 长期记忆查看/删除入口） | **仍在，待产品决策** | 无任何 API/前端入口；`delete_fact` 无 user_id 作用域（仅内部裁剪调用，暂无越权面） |
| 新增 | **N1–N6 + R11（`MEMORY_MIN_SIM=0.35` 未校准）、R12（AGENTS.md 自动区未刷新）** | 见第四节；建议提交前跑 `python scripts/gen_agents_doc.py` 或依赖 pre-commit 钩子 |

**给收尾的明确建议**：
1. 若要绿灯：人工书面追认 R5（并在 proposal 风险 7 标注「未实测、采用合并方案」），并决定 R6/R7 是否本轮固化；同时建议顺手清掉 N4 的残留行、刷新 N3 的 `test_plan.md` 期望值、消除 N5 的重复常量。
2. N1/N2/N6 可放入 `context/risk-ledger.md` 作为后续小修，不构成本轮阻塞。

## 附：本轮复验执行过的命令清单（可复核）

```
git status --short / git diff --stat / git diff backend/api/streaming.py / git diff backend/agent/graph.py
git diff backend/tracing/collector.py / git diff backend/store/db.py / git diff backend/store/__init__.py
git diff backend/agent/prompts.py / git diff frontend/src/*.tsx / git diff frontend/src/types.ts / git diff frontend/src/styles.css
# test_plan 第一节 7 条（逐条执行并记录退出码）
.venv/bin/python -c "import backend.main"
.venv/bin/python -m pytest test/test_memory.py -v      # 14 passed
.venv/bin/python -m pytest -q                          # 14 passed, 1 warning
.venv/bin/python -m backend.eval.prompt_eval           # 全 ✓
cd frontend && npm run typecheck && npm run build      # 均 exit 0
.venv/bin/python -c "PRAGMA table_info(memories) / sqlite_master / COUNT(*)"
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8124 + curl -i /api/runs, curl /  （验后 kill）
# 对抗性验证（均以 `.venv/bin/python - <<'PY'` 内联执行，未落盘任何脚本/未改任何产品代码）
R1: 注入 list_facts 抛错 / embed_texts 返回 [] / 返回 0 向量 / embedding 损坏 / context.recall_facts 抛错
    / summarize_history 抛错 / 两者同时抛错 / 真实 embed 假 key；以 streaming 式驱动判定是否产 error 事件
R1-h: recall_facts(query=None) vs assemble(query=None)  —— 证明二层兜底确有必要
R2: 90KB base64 的 history_chars / 8 种消息形态 parity / 走 assemble 的摘要与落库计数 / 13000 字反向触发
R3: n=2/16/17/20 边界的摘要调用与落库；真实落库 → 次轮注入 → 再下一轮不覆盖；跨 session 隔离
R4: 4 个指定输入 + 8 个对抗性边界输入；旧 lstrip 实现突变反证
R8: .venv/bin/python -W error::RuntimeWarning 同步上下文 + gc 扫描未 await 协程；循环内正向路径与早退分支
回归: message_text vs extract_text_content 口径；summarize_history transcript 抓取；history_chars 新旧语义对比
其他: 用户隔离复跑 / 迁移幂等 ×3 / _evict_overflow 裁剪 / memories 残留行检查 / 是否有 memory 路由 / requirements 与 package.json diff
```

> 本轮复验**未修改任何产品代码**；写入的文件仅为本节所追加的 `test_report.md`（`git status` 复核仍为 11 modified + 5 untracked，与复验前一致）。

---

# 修复记录（修复轮次 2）

> 修复人：写代码 agent ｜ 触发：复验（轮次 2）判 🟡 黄
> 说明：N1 属**确定性 bug**（非风险），直接修；N3/N4 为流程产物问题，一并处理。

| 项 | 问题 | 处理 |
|----|------|------|
| **N1** | R4 修复不彻底：`3.14是圆周率`→`14是圆周率`、`-5度以下偏好`→`5度以下偏好`、`2、3线城市`→`3线城市` | 正则改为**「标记必须后跟空白」**：`^\s*(?:[-•*]+\s+|\d+[.、)]\s+)`，只剥 `- 条目` / `1. 条目` 这类真列表项；`test_parse_facts_keeps_leading_digits` 扩展到 7 种输入（年份/数量/小数/负号/顿号连接/真列表/真序号） |
| **N3** | `test_plan.md` 期望值过期（#2 仍写 9 passed、#6 行数旧） | 已更新为 **14 passed** + 最新行数 |
| **N4** | 上一轮复现时把伪造摘要写进了**开发库**：`memories(user_id='no-such-user', kind='summary', content='【模型对空对话生成的摘要】')` | 已删除（清理前 1 行 → 清理后 0 行） |

**修复后自测**：`.venv/bin/python -m pytest test/test_memory.py -q` → **14 passed in 0.59s**。

## 仍待人工决定（风险/产品决策，非 bug）

- **R5**：`【推理生成】` 标注 + proposal 风险 7「多条 system 兼容性未实测即采用合并方案」→ 需**书面追认**；
- **R6**：`pytest` 未写入 `requirements.txt`（仓库无 dev 依赖文件）→ 是否固化；
- **R7**：`extract_facts` / `schedule_extraction` / graph-streaming 集成仍无用例 → 是否补；
- **R10**：长期记忆明文落库、用户无自助查看/删除入口 → 产品/合规决策；
- **R11**：`MEMORY_MIN_SIM=0.35`、`FACT_DEDUP_SIM=0.92` 未经真实数据校准；
- **R9 / N2 / N5 / N6**：断连丢尾部抽取；`context` 层兜底无用例；两处 `KEEP_TAIL` 常量重复；「条数少但单条极长」时预算不生效（R3 的有意代价）。

## 状态

N1/N3/N4 已处理，机器项自测全绿。**按 SOP，黄灯不强制阻塞**：是否再走一轮 3.3 复验、以及 R5/R6/R7/R10/R11 的处置，请人工裁决。

---

# 修复记录（修复轮次 3）· R5 实证结案

> 触发：人工授权写代码 agent 使用应用自身 `resolve_api_key()` 解出 ApiKey（进程内、不打印明文），对 DashScope 做真实探测。

## R5 结论：**支持多条 system，原合并方案多余，已移除**

| 探测项 | 结果 |
|--------|------|
| 1 条 system | HTTP 200 |
| 2 条连续 system（开头） | HTTP 200 |
| 尾部 system（human 之后） | HTTP 200 |
| 中间 system | HTTP 200 |
| 双开头 + 尾部 system | HTTP 200 |
| 全部在册模型（逐个实测） | qwen3.7-plus / qwen-plus / qwen-turbo / deepseek-v4-pro / deepseek-v4-flash / deepseek-v3 / deepseek-r1 / glm-5 **全部 200**；qwen-max 返回 403（Free quota exhausted，**配额问题，非 system 问题**） |

**因此**：proposal 风险 7「多条 system 未实测」**已由实测排除**；原先为兼容而加的 `merge_system_messages` 是**基于错误假设的多余防御**，且它使 trace 记录的结构 ≠ 真实发送的报文（保真度受损）。

## 本次改动

| 项 | 处理 |
|----|------|
| `backend/agent/context.py` | 删除 `merge_system_messages`（207 行） |
| `backend/agent/graph.py` | `llm.ainvoke(messages)` 直接发送原样 messages；去掉 import；注释更新为「实测支持多条/任意位置 system，原样发送、trace 保真」 |
| `test/test_memory.py` | 删除对应用例（14→**13 passed**）；清理不再使用的 `SystemMessage` import |
| **R5 状态** | 🔴→**已关闭（实测排除，无需人工追认）** |
| **【推理生成】标注** | 随该函数一并消失，`context.py` 现有【推理生成】清零 |

**自测**：`import` OK / `pytest` **13 passed** / `prompt_eval` 全通过 / 前端 `typecheck` 通过 / `grep merge_system_messages` 无残留。

---

# 附带发现 · RAG 评测首次真实跑通（Phase 1 遗留人工项）

用同一 key 首次真实执行 `rag_eval`（16 条），结果：

```
top_k = 5, num_queries = 16
recall@5 = 0.311     ← 低于此前约定的「合理线」(≥0.5)
MRR      = 0.620     ← 尚可（首个命中通常靠前）
nDCG@5   = 0.377
完全未命中 4/16：含免费早餐 / 精品设计风格 / 太空针塔塔景 / 带餐厅
```

**判断：这不只是检索问题，更暴露了评测集标注方法论的缺陷。** 以「太空针塔附近可以看塔景」为例——
golden 标的是 `[Pan Pacific, Hyatt Place, Holiday Inn Seattle Downtown]`，而检索返回的是
`[Travelodge by The Space Needle, Mediterranean Inn, Executive Inn By The Space Needle ...]`：
**后者确实都在太空针塔旁、名字里就带 Space Needle**，判为「未命中」是 golden 标注过窄所致。
「带餐厅」「含免费早餐」同理——语料里几十家酒店都有餐厅，golden 只标了 4 家，返回其它符合条件的酒店被算作 miss。

→ 结论：**评测集对「宽泛属性类 query」需要放宽 golden 或改写 query**（属 Phase 1 评测集迭代，不在本次变更范围）。
该发现已记入本报告，建议后续单开变更处理；Phase 1 「指标是否合理」这一人工验收项**至此跑通并有基线数据**。

## 状态

R5 已实证关闭；机器项全绿。剩余待人工决定项不变：**R6**（pytest 依赖固化）、**R7**（补 `extract_facts`/`schedule_extraction`/集成用例）、**R10**（长期记忆用户可见/可删）、**R11**（阈值校准），以及上述 **RAG 评测集放宽**（新发现）。




---

# 独立验证报告 · 20260919-101804-memory-manage

> 验证人：独立验证 agent（未参与编码）
> 验证时间：2026-09-19 10:24:48
> 验证对象：工作区**未提交**改动（`git status` 15 modified + 8 untracked；`git log` 最新 commit 为 `723c31c`，本变更及上一变更 `memory-phase2` **均无 commit 边界**）
> 依据：`context/rule/review.md`、`context/rule/coding.md`、本目录 `proposal.md` / `feature.md` / `test_plan.md`，以及 `20260918-175408-memory-phase2/test_report.md`（来源 R10）
> 方法：逐条亲自执行机器验证；**自己写脚本**做对抗性证伪（越权 / 隔离 / 向量泄露 / 级联 / 锁 / 边界 / 参数篡改 / token 伪造）；所有探测均在**临时隔离库**（运行时改写 `store.db.DB_PATH`）中执行，未污染开发库。
> 环境：Python 3.12.13（`.venv`）、pytest 9.1.1、Node v26.5.0、httpx 0.28.1、FastAPI TestClient。

## 结论：🔴 红

**机器可查 8 项全绿（16 passed / typecheck / build / 401 鉴权全过），对抗性安全验证 12 组全部通过（越权、隔离、embedding 剥离、级联范围、锁重入、并发、边界、参数篡改、token 伪造均无问题）。但 proposal 第 2 节有 2 条验收标准在可达路径上未达成：**

| 编号 | 未达成项 | 级别依据 |
|------|----------|----------|
| **B1** | **删除会话（全新库 / 未配置 ApiKey 场景）返回 500，且本次新增的「级联清理 summary」根本没执行 → 验收标准 4「删会话级联清摘要、不留孤儿」未达成**（已用真实 HTTP 路径端到端复现，并暴露「500 但会话行半删」的数据一致性副作用） | `review.md` §一「验收标准有未达成项 → 红」 |
| **B2** | **「记忆列表（内容 + 时间）」的「时间」前端完全未渲染 → 验收标准 1 未达成**（静态确证：`frontend/src/components/MemorySection.tsx` 全文未使用 `created_at`/`createdAt`） | 同上 |

按 `review.md` §一：**必停 —— 不修不往下走，停下问人。** 两处修复合计约 3–5 行（见第五节），且 **B1 的根因是本次改动之前就存在的代码**（`HEAD` 版 `delete_session` 即有无保护的 checkpoint 删除），本次新增的级联 SQL 排在其后，导致新功能在该路径被吞掉。

> 说明（避免误读）：本次变更**自身写的代码经对抗性验证是正确的**——越权删除被拒、清空只清本人、向量不泄露、级联只清本会话 summary、无 `_lock` 重入死锁。判红只因上述两条**验收标准字面未达成**，不是本次新增逻辑有安全漏洞。

---

## 一、机器验证结果（test_plan 第一节 8 条，逐条亲自执行）

| # | 命令 | 真实输出摘要 | 退出码 | 通过 |
|---|------|--------------|--------|------|
| 1 | `.venv/bin/python -c "import backend.main"` | 无任何输出（无异常） | 0 | ✅ |
| 2 | `.venv/bin/python -m pytest test/test_memory.py -v` | `collected 16 items` → **`16 passed in 0.40s`**；16 条用例名逐一列出，含 `test_delete_fact_owned_rejects_other_user` / `test_delete_all_facts_only_own` / `test_delete_session_cascades_summary_but_keeps_facts` | 0 | ✅ |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.0.0`；身份/行为/输出格式/信息补充 4 层全 `[✓]`；`结果：全部通过` | 0 | ✅ |
| 4 | `cd frontend && npm run typecheck` | `tsc --noEmit` 零输出（无 TS 报错） | 0 | ✅ |
| 5 | `cd frontend && npm run build` | `vite v5.4.21` → `✓ 2380 modules transformed` → `✓ built in 3.03s`，产出 `dist/assets/index-DP3JdQ1m.js` (372.25 kB) / `index-CRdDIvai.css` (33.14 kB)。仅既有 `>500 kB` chunk 提示，非错误 | 0 | ✅ |
| 6 | 路由注册（`app.routes` 内省，非读文档） | `['GET'] /api/memory`、`['DELETE'] /api/memory/{fact_id}`、`['DELETE'] /api/memory` —— 三条**全部注册** | 0 | ✅ |
| 7 | 未登录 `curl` 三条 `/api/memory*` | `GET /api/memory` → **401** `{"detail":"未登录"}`；`DELETE /api/memory/whatever` → **401**；`DELETE /api/memory` → **401** | 0 | ✅ |
| 8 | 文件行数 | `SettingsModal.tsx` **245**、`MemorySection.tsx` **92**、`api/routers/memory.py` **48**、`store/memory.py` **128** —— 四项**全部 ≤300** | 0 | ✅（另见 Y1：`styles.css` 存量超限且增长） |

**补充回归（全量 pytest）**：`.venv/bin/python -m pytest -q` → **`16 passed, 1 warning in 0.54s`**，退出码 0。唯一 warning 来自第三方 `pydantic_settings`（`IncompleteFieldDefinitionWarning: Field 'lifespan'`），与本变更无关。

### 验证命令的环境事实
- `pytest` 已装 `.venv`（9.1.1）但 **`requirements.txt` 未声明**；仓库无 `requirements-dev.txt` / `pyproject.toml` / `setup.py` / `setup.cfg`（实测 `grep -rn "pytest" requirements*.txt pyproject.toml setup.py setup.cfg` → 无命中）。→ **沿用上一轮 R6，本次同样计入（Y4）**：他人按 `requirements.txt` 装完跑不了这 16 条用例。
- `frontend/dist/` 已由本次验证的 `npm run build` 重新生成（属 gitignore 产物，不入库）。
- 被验证进程为**开发机已在跑的 uvicorn**（127.0.0.1:8000，reload 父子两进程）：`/api/memory` 未登录返回 **401** 而非 SPA 兜底的 404 → 证明**运行中的实例已加载新路由**（本变更未提交也已生效）。

---

## 二、对抗性安全验证（自己写脚本，证据均可复核）

> 全部脚本以 `.venv/bin/python - <<'PY'` 内联执行，**未落盘任何脚本、未改任何产品代码**；每个脚本先把 `backend.store.db.DB_PATH` 指向 `tempfile.mkdtemp()` 下的新库并清空 `_conn` 缓存，再用 `fastapi.testclient.TestClient` 走**真实 FastAPI 路由 + 真实 JWT 依赖**（用 `auth.tokens.create_token` 为 A/B 两个真实用户签发 token）。

### 1. 越权删除（A/B 两用户）— ✅ 通过

```
=== T1 store.delete_fact_owned(B, A的fact) ===
  delete_fact_owned(B, A的fact) = False   (期望 False)
  A 记忆仍在: ['A-秘密-1']  count=1
  -> PASS: 越权被拒且 A 记忆未受影响

=== T3 HTTP 越权删除 ===
  B DELETE /api/memory/{A的id} -> 404 {"detail":"记忆不存在或无权访问"}
  A 记忆仍在: ['A-秘密-2']
  -> PASS: 404 且 A 记忆仍在
```
- 代码侧交叉核对：`store/memory.py:111-117` 把归属写进 `WHERE id = ? AND user_id = ? AND kind = ?`，`return cur.rowcount > 0`；router `memory.py:40-41` 依返回值抛 404（不泄露存在性）。**代码与实测一致。**
- 边界：**A 拿自己的 token 去删自己的 summary 行 id / B 的 summary 行 id，均 404**（`kind='fact'` 过滤生效，摘要不可经此 API 删除）。

### 2. 清空隔离 — ✅ 通过

```
=== T2 store.delete_all_facts(A) ===  返回 1；A count=0   B count=1 B记忆=['B-秘密-1']
=== T5 HTTP DELETE /api/memory ===    {"ok":true,"deleted":2} → A count=0  B count=1
```
> 注：T5 的 `deleted=2` 是因为 T1/T3 之后 A 又新增了一条，非重复删除。

### 3. 「GET /api/memory 不含 embedding」— ✅ 通过（两条路径均已验）

**路径一（HTTP 报文级）**：单条字段集合实测 = `['content', 'created_at', 'id']`，与期望三元组**严格相等**；对原始响应文本 `resp.text` 搜索泄露关键词 `["embedding","0.111111","0.222222","0.333333","[0.111"]` → **命中 0 个**。
```json
{"facts": [{"id": "mem-a1c141b6022643e59f665c349be07205", "content": "A-秘密-2", "created_at": 1789784457.8002188}], "total": 1}
```
**路径二（store 层对照，证明「真剥离」而非「本来就无向量」）**：
```
[对照] store.list_facts(A)[0] 字段 = ['content', 'created_at', 'embedding', 'id'], embedding=[0.111111, 0.222222, 0.333333]
```
→ `store.list_facts` 确实返回向量，router `memory.py:23-30` 逐字段白名单重建（只取 id/content/created_at），**剥离发生在 router 层且是显式白名单（新增字段不会自动外泄）**。另有 router 静态审查：全文无 `embedding` 字样。

### 4. `delete_session` 级联清理范围 — ✅ 通过（仅限 checkpoints 表存在时；反面见 B1）

在临时库中补建 `checkpoints` / `writes`（复刻真实库环境）后：
```
=== T6 越权删会话 ===
  delete_session(B,A的SA1)=False  delete_session(A,B的SB1)=False (均期望 False)
  A/SA1 在=True 摘要='A-S1摘要'   B/SB1 在=True 摘要='B-S1摘要'

=== T7 级联清理范围 ===   delete_session(A,SA1)=True 耗时 0.08 ms
  ✅ A/SA1 summary 已清
  ✅ A/SA2 summary 保留
  ✅ B/SB1 summary 保留
  ✅ B/SB1 会话行保留
  ✅ A 两条 fact 全保留
  ✅ A-绑会话 fact 保留          ← 对抗性：手工插入 kind='fact' 但 session_id=SA1 的行，验证不会被误删
  ✅ A/SA1 checkpoint 已清
  ✅ B/SB1 checkpoint 未受影响
  ✅ A/SA1 session 行已删
```
**结论**：级联**只**清 `user_id + session_id + kind='summary'`；跨会话 fact、甚至「被人为绑定了 session_id 的 fact」都保留；他人同/异名会话数据与 checkpoint 均不受影响。与 `sessions.py:89-95` 的 SQL 及注释完全一致。

### 5. `_lock` 重入死锁 — ✅ 通过（且证明该检查有意义）

```
=== T8 _lock 重入死锁 ===
  同线程首次 acquire=True  再次 acquire=False  (True/False = 锁不可重入，重入写法必死锁)
  真实 delete_session：5s 内完成=True 返回=True 耗时=0.10 ms
```
- **对抗性控制实验**：先在**同一线程**连续 `_lock.acquire(blocking=False)` 两次 → 第二次返回 `False`，**证明 `threading.Lock` 不可重入**，因此「在 `with _lock` 内再调用任何取 `_lock` 的 store 函数」必然永久死锁。
- 反向证伪（意外但有力的证据）：第一版控制实验写成 `with _lock: with _lock: pass` 放在常驻线程里，**整个探测进程随即被永久挂死（60s 超时被 SIGTERM）** —— 这正是重入死锁的真实后果，也说明该检查项不是走过场。
- 真实 `delete_session` 在**线程 + `join(5)` 超时**下 0.10 ms 返回，且 `sessions.py:85-95` 使用的是**内联 SQL**（注释亦写明「此处已持有 `_lock`，直接执行 SQL」），**未调用任何会再次取锁的 store 函数**。→ **无重入死锁**。

### 6. 并发压力 — ✅ 通过
```
=== T9 并发压力 20 线程 ===  完成 20/20；异常=[]；耗时=8.7 ms
```
20 线程混合执行 `create_session / save_summary / add_fact / delete_session / delete_all_facts` → 无异常、无死锁、无线程滞留。

### 7. 边界与畸形输入 — ✅ 通过

| 输入 | 实测结果 | 判定 |
|------|----------|------|
| 不存在的 `fact_id` | `404 {"detail":"记忆不存在或无权访问"}` | ✅ |
| **空 `fact_id`**（`DELETE /api/memory/`） | `405 Method Not Allowed`，**重定向链为空**，且随后 `A facts=2` **未被清空**（重点：确认尾斜杠不会被 307 重定向成「清空全部」这一危险语义） | ✅ |
| 纯空格（`%20`） | `404` | ✅ |
| **SQL 注入** `' OR '1'='1` | `404`，A 记忆完好（`WHERE` 参数化绑定） | ✅ |
| 超长 5000 字符 `fact_id` | `404`，无 500、无异常 | ✅ |
| A 自己的 summary 行 id | `404`（`kind` 过滤挡住） | ✅ |
| 别人的 summary 行 id | `404` | ✅ |
| A 的 fact id + **B 的 token** | `404`，A 记忆仍在 | ✅ |

### 8. 鉴权 / 方法 / 参数篡改 / 伪造 token — ✅ 通过

```
=== T11 鉴权/方法矩阵 ===
  无 token GET /api/memory -> 401 ; DELETE /api/memory -> 401 ; DELETE /api/memory/mem-x -> 401
  已登录 POST /api/memory -> 405 ; PUT -> 405 ; PATCH -> 405
  伪造 token -> 401 ; 空 Bearer -> 401

=== 参数篡改（企图指定他人 user_id）===
  A 的 token GET  /api/memory?user_id={B} -> 200 只返回 A 的事实
  A 的 token DELETE /api/memory?user_id={B} -> {"ok":true,"deleted":1}（删的是 A 自己的）
  结果：A facts=0  B facts=1  → query 参数被完全忽略，身份只来自 JWT
  另一密钥签名 token -> 401 ; alg=none token -> 401
```
- `auth/deps.py:16-20` 对「无凭证 / 空凭证 / `sub` 解不出」三种情况均 401；实测伪造签名与 `alg=none` 均被 `PyJWT` 拒。
- **日志泄露面**：`grep -n "logging|logger|print(" backend/store/memory.py backend/api/routers/memory.py` → **无任何日志/打印语句**，记忆明文不写日志（`review.md` 安全检查项通过）。

### 9. 响应格式 / 空态（旧接口兼容性）— ✅ 通过
```
GET(1条)        -> {"facts":[{"id":"mem-...","content":"A-最后","created_at":1789784592.171554}],"total":1}
DELETE {id}     -> {"ok":true}
GET(空态)       -> {"facts":[],"total":0}
DELETE all(空)  -> {"ok":true,"deleted":0}
```
新增路由不影响任何既有接口返回格式（`/api/runs`、`/api/sessions` 等形状未变，见第三节）。

---

## 三、回归检查

### 3.1 既有接口（登录态，TestClient 真实路由）
| 接口 | 结果 | 判定 |
|------|------|------|
| `GET /api/models` | 200（模型列表） | ✅ |
| `GET /api/modes` | 200 | ✅ |
| `GET /api/sessions` | 200 `{"sessions":[]}` | ✅ |
| `GET /api/runs` | 200 `{"runs":[],"total":0,"limit":50,"offset":0}` | ✅ |
| `GET /api/usage` | 200 | ✅ |
| `GET /api/settings` | 200 | ✅ |
| `GET /api/mcp/servers` | 200 | ✅ |
| `GET /api/files/limits` | 200 | ✅ |
| `GET /api/runs/{不存在}` | 404 `{"detail":"trace 不存在或无权访问"}` | ✅ |
| `GET /api/sessions/{不存在}/messages` | 404 `{"detail":"会话不存在或无权访问"}` | ✅ |
| `GET /api/nope` | 404 `{"detail":"Not Found"}` | ✅ |

### 3.2 SPA 路由与静态入口（curl 实测 + `App.tsx` 静态核对）
| 路径 | HTTP | 说明 | 判定 |
|------|------|------|------|
| `/` | 200 `text/html`（400 B，即刚构建的 `index.html`） | ✅ |
| `/traces` | 200 `text/html` | `App.tsx:284` `path="/traces"` 真实路由 | ✅ |
| `/badcases` | 200 `text/html` | **`App.tsx` 无此路由**，由 `path="*"` 兜底重定向到 `/`；`App.tsx` 本次未改动（不在 `git status`），属**既有行为，非本次回归** | ✅（附注） |
| `/api/runs`（未登录 curl） | 401 `{"detail":"未登录"}` | ✅ |
| `GET /`（未构建提示分支） | 已构建，故 200（503 分支未触发） | ✅ |

### 3.3 全量测试
`.venv/bin/python -m pytest -q` → **16 passed, 1 warning**，退出码 0。仓库当前仅 `test/test_memory.py` 被收集（`test/` 下无其他测试文件）。

---

## 四、验收标准对照（proposal 第 2 节）

| # | 验收标准 | 状态 | 依据 / 原因 |
|---|----------|------|-------------|
| 1 | 设置弹窗可列出当前用户的全部长期事实记忆（**内容 + 时间**），不含向量 | **❌ 未达成（缺「时间」）** | API 侧**已达成**：`GET /api/memory` 返回 `id/content/created_at`，实测无 embedding（第二节 3）。前端侧**未达成**：`MemorySection.tsx` 只渲染 `m.content` 与条数，**全文未使用 `created_at`**（`grep -rn "created_at\|createdAt" frontend/src/` 命中的 6 处均在 `types.ts` / `TracesPanel.tsx` / `RunDetail.tsx`，**无一处是记忆列表**）。`MemoryFact.created_at` 为「已声明未使用」的死字段。→ 见 **B2** |
| 2 | 可单条删除；可一键清空（**带二次确认**） | **✅ 达成（前端交互属人工项）** | 后端两条路由实测可用（第二节 1/2/7）；前端 `MemorySection.tsx:44` 的 `confirm("确定清空全部长期记忆吗？…")` 构成二次确认，单条删除走 `handleDelete` + 本地 state 收敛。真实点击效果需人工目视 |
| 3 | 所有接口严格按 `user_id` 隔离，删除他人记忆返回 404（不可越权） | **✅ 达成** | 越权 `delete_fact_owned`→`False`、HTTP→`404` 且他人数据完好；`delete_all_facts` 只清本人；`?user_id=` 参数篡改被忽略；伪造/`alg=none` token→401（第二节 1/2/8） |
| 4 | 删除会话时，该会话的滚动摘要（`kind='summary'`）被级联清理，不留孤儿 | **❌ 未达成（存在可达失败路径）** | **正常路径已达成**：checkpoints 表存在时 9/9 项检查通过（第二节 4）。**失败路径未达成**：全新库（`checkpoints` 表尚未由 `AsyncSqliteSaver` 创建）执行 `DELETE /api/sessions/{id}` → **HTTP 500**，新增的级联 DELETE 排在抛异常的语句之后**根本没执行**，summary 成为孤儿。**已用真实 HTTP 路径端到端复现**（见下 B1 证据） |
| 5 | 记忆为空时前端有明确空态提示 | **✅ 代码确证（渲染需人工）** | `MemorySection.tsx:66-67`：`memories.length === 0` → `<div className="memory-empty">系统还没有为你保存任何长期记忆</div>`，非空白/非报错；CSS `.memory-empty` 已定义（`styles.css:1077`）。实测空态 API 返回 `{"facts":[],"total":0}`。**但**：拉取失败也会落到同一空态（见 Y2） |
| 6 | 至少 1 条 pytest 覆盖「越权删除被拒」与「清空只清本人」 | **✅ 达成** | `test_delete_fact_owned_rejects_other_user`、`test_delete_all_facts_only_own`、`test_delete_session_cascades_summary_but_keeps_facts` 三条均实跑通过（16 passed）。用例断言方向正确（断言「返回 False」+「原记忆仍在」+「他人 count 不变」），非「不抛错即通过」式的同义反复 |

### B1 复现证据（本人执行，端到端真实 HTTP）

路径：**全新库 + 用户未配置 ApiKey** → 前端生成 `session_id` 并发送消息 → 后端在解析 ApiKey **之前**已 `create_session`（`streaming.py:237` 先于 `:241` 的 `resolve_api_key`）→ 会话行已存在并出现在侧栏，而创建 checkpoint 表的 `get_graph()`（`streaming.py:263`）**未被执行** → 用户从侧栏删除该会话。

```
[全新库] checkpoints 存在 = False

场景：全新库 + 用户未配置 ApiKey → 发一条消息（会话行被创建）
  POST /api/chat -> 200 'data: {"error": "尚未配置模型 ApiKey，请先在「模型设置」中填写"}\n\ndata: [DONE]\n\n'
  [之后] checkpoints 存在 = False
  侧栏 GET /api/sessions -> {"sessions":[{"id":"sess-5cd5cd80...","user_id":"usr-3c08cf3b79c5","title":"你好",...}]}

用户从侧栏删除这个会话（真实 HTTP 路径）
  ** DELETE /api/sessions/{id} -> 500 Internal Server Error
  共享连接可见 sessions 行 = 0 (0=已执行DELETE，可能未提交)
  另一连接可见 sessions 行 = 1 (1=未落盘)
  侧栏再查 -> {"sessions":[]}
```

根因（`store/sessions.py:87-95`，`HEAD` 版即存在）：
```python
for tbl in ("checkpoints", "writes"):
    conn.execute(f"DELETE FROM {tbl} WHERE thread_id = ?", (tid,))   # ← 表不存在时抛 sqlite3.OperationalError
# 级联清理该会话的滚动摘要 ...（本次新增）
conn.execute("DELETE FROM memories WHERE user_id = ? AND session_id = ? AND kind = 'summary'", ...)
```
- 孤立复现（store 层）：`sqlite3.OperationalError: no such table: checkpoints`（`backend/store/sessions.py:88`）。
- **三个后果**：① HTTP 500（用户以为删除失败）；② 本次新增的 summary 级联**永不执行** → 孤儿摘要；③ `conn.commit()` 未执行但 `DELETE FROM sessions` 已在连接事务内 → **半截删除**：共享连接看不到该行（UI 侧栏显示已删成功），磁盘上仍在，**之后任意一次无关 store 写操作的 `commit()` 会把它顺带真正删掉**（实测：另一连接在 `add_fact` 后由 1 变 0）。这是「失败却留下半截数据」的一致性缺陷。
- **同一文件里 `db.py:57-64` 对完全相同的两张表已用 `try/except sqlite3.OperationalError` 兜底并注释「表尚不存在（全新库）」** —— 说明作者已知该风险，只是 `delete_session` 漏了同样的保护。
- 影响面界定：`deploy/deploy_local.sh:67` 用本地库 `.backup` 生成部署包（真实开发库实测含 `checkpoints`/`writes`，各 112 行），故**当前部署链路不受影响**；受影响的是 **`git clone` 全新环境**（`data/openunknown.db` 已被 `.gitignore` 排除，`git ls-files data` 仅含 hotels 两个文件）、CI、以及任何未产生过 checkpoint 的库。

---

## 五、行数合规（`coding.md` §3）

| 文件 | 当前 | `HEAD` | 判定 |
|------|------|--------|------|
| `frontend/src/components/SettingsModal.tsx` | 245 | 242 | ✅ ≤300 |
| `frontend/src/components/MemorySection.tsx` | **92** | 新增 | ✅ ≤300 |
| `backend/api/routers/memory.py` | **48** | 新增 | ✅ ≤300 |
| `backend/store/memory.py` | **128** | 新增（上一变更产物） | ✅ ≤300 |
| `backend/store/sessions.py` | 97 | 90 | ✅ ≤300 |
| `backend/store/__init__.py` | 82 | 64 | ✅ ≤300 |
| `backend/main.py` | 77 | 66 | ✅ ≤300 |
| `frontend/src/types.ts` | 219 | 210 | ✅ ≤300 |
| `frontend/src/api/endpoints.ts` | 259 | 241 | ✅ ≤300 |
| `backend/agent/prompts.py` | 109 | 87 | ✅ |
| `backend/tracing/collector.py` | 207 | 200 | ✅ |
| `backend/store/db.py` | 235 | 217 | ✅ |
| `backend/api/messages.py` / `backend/agent/context.py` / `backend/agent/memory.py` / `test/test_memory.py` | 122 / 207 / 218 / 267 | 新增 | ✅ ≤300 |
| `backend/agent/graph.py` | 343 | **431** | ⚠️ 超 300，但 **下降 88 行** → §3 满足 |
| `backend/api/streaming.py` | 356 | **431** | ⚠️ 超 300，但 **下降 75 行** → §3 满足 |
| `frontend/src/styles.css` | **1087** | **1064** | ❌ **存量超限（>300）且本次 +23 行** → 字面违反 §3「存量文件已超限时，本次改动不得再增加行数」→ 见 **Y1** |

> `styles.css` 的 +23 行即本次新增的 `.memory-*` 样式（`styles.css:1071-1087`，7 个类全部已定义且与 `MemorySection.tsx` 使用的类名**一一对应**，无未定义类、无死样式）。上一轮 `memory-phase2` 报告的行数节只统计 `.py`，未对 CSS 做同样核算 —— **是否把 CSS 纳入 §3 属口径问题，需人工裁决**（见第六节）。

---

## 六、风险清单

| ID | 风险 | 级别 | 说明 / 影响面 / 建议 |
|----|------|------|----------------------|
| **B1** | **全新库删会话 500 + 级联未执行 + 半截删除** | 🔴 阻塞（验收标准 4 未达成） | 见第四节 B1 证据。**修复建议（约 3 行）**：把 `for tbl in ("checkpoints","writes")` 的删除包进 `try/except sqlite3.OperationalError`（照抄 `db.py:57-64` 的既有做法），或把记忆级联 DELETE 提到该循环**之前**；建议同时给「表不存在」补一条 pytest（当前 3 条新用例都在 `checkpoints` 表已存在的假定下运行，**该缺陷无用例覆盖**）。根因非本次引入，但**必须修**才能让本次验收标准 4 成立 |
| **B2** | **记忆列表不显示时间** | 🔴 阻塞（验收标准 1 未达成） | `MemorySection.tsx` 未渲染 `created_at`（`types.ts:218` 已声明）。**修复建议（1 行）**：在 `memory-text` 旁加形如 `new Date(m.created_at * 1000).toLocaleString()` 的时间（`TracesPanel.tsx:124` 已有同款写法可复用）。若人工认定「API 已返回时间即视为达标」，需**书面追认**并同步修改 proposal 该行措辞 |
| **Y1** | `styles.css` 存量超限且增长（1064 → 1087） | 🟡 | 是否将 CSS 纳入 `coding.md` §3 的 300 行约束需人工定口径。若纳入，本次 +23 行需拆分（如新增 `memory.css` 由 `main.tsx` 引入） |
| **Y2** | **拉取失败与空态不可区分** | 🟡 | `MemorySection.tsx:26-28` 的 `.catch(() => setMemories([]))` 把网络/401 失败静默降级成「系统还没有为你保存任何长期记忆」——用户会误判为「系统没记我的事」，与 proposal §6 风险 2「空态/失败态需处理」**未排除**。建议加失败态文案与重试 |
| **Y3** | **「清空全部」不清会话摘要，文案可能过度承诺** | 🟡 | 实测：`DELETE /api/memory` → `{"deleted":1}` 后，同一 `memories` 表里 `kind='summary'` 的会话摘要**仍在**（实测 `load_summary = '用户聊过银行卡尾号 1234'`），且不暴露在任何列表里。即用户点了「清空全部长期记忆」，系统仍保留着含对话内容的摘要并在后续对话中注入。proposal 只把 fact 定义为「长期记忆」故符合设计，但从 R10 的隐私语义看属**静默保留**，需产品决策（至少改文案或提供清空摘要入口） |
| **Y4** | `pytest` 未写入 `requirements.txt` | 🟡（沿用上轮 R6） | 本次仍无 `requirements-dev.txt`；他人按 README 装依赖后**跑不了这 16 条用例**，绿灯门槛「≥1 条 pytest」在他人环境不可复现 |
| **Y5** | **`feature.md` 的 diff 数字不可复现；两变更无 commit 边界** | 🟡（流程） | `feature.md` 称「7 个已跟踪文件 `+158 / −2`」；本人对同一 7 个文件实测 `git diff --numstat` = **+90 / −1**（main.py 12/1、store/__init__.py 18/0、sessions.py 7/0、endpoints.ts 18/0、SettingsModal.tsx 3/0、styles.css 23/0、types.ts 9/0）。且 `memory-phase2` 与 `memory-manage` **同时停留在工作区**（15 modified + 8 untracked，无任何 commit），**无法按变更拆分 diff**，`+158/−2` 既不可证实也不可证伪。建议提交时拆 commit |
| **Y6** | 人工项未做 | 🟡（无法验证） | `test_plan.md` 第四节「设置弹窗真实渲染、删除与清空的实际交互、空态展示效果」本轮**未执行**（需真实登录浏览器），故验收标准 2/5 的**渲染层**记为「代码确证 / 交互无法验证」，不记为「已达成」 |
| **Y7** | `MemorySection.tsx` 注释与事实不符 | ⚪ 提示 | 文件头注释写「从 SettingsModal 拆出（该文件已超 300 行…）」，但 `SettingsModal.tsx` 实测 245 行、`HEAD` 242 行，**从未超 300**（真实原因是内联版本一度达 312 行，见 `feature.md` 偏差 1）。建议改为「拆出以避免超过 300 行」，属注释准确性问题 |
| **Y8** | AGENTS.md 自动生成区未刷新 | ⚪ 提示（沿上轮 R12） | §5 路由表无 `/api/memory`、§8 文件清单无 `api/routers/memory.py` / `MemorySection.tsx` / `store/memory.py` 等。按 `AGENTS.md` §7，提交前 pre-commit 钩子会自动刷新，无需手改 |
| **Y9** | `/badcases` 不是真实前端路由 | ⚪ 提示（既有） | `App.tsx` 只有 `/` 与 `/traces`，`/badcases` 由 `path="*"` 兜底重定向；`App.tsx` 本次未改动 → 非回归。但 `test_plan.md` 把 `/badcases` 列为回归项，**该期望值本身可疑**（建议确认它是否应存在） |
| **Y10** | 「清空」后不刷新、失败静默 | ⚪ 提示（UX） | 记忆列表只在 `open` 变化时拉取；设置弹窗保持打开期间若产生了新记忆不会自动刷新。删除/清空失败仅 `catch {}` 静默（`MemorySection.tsx:38/50`），用户无感知 |

### 已确认无问题的项（正向记录，避免重复质疑）
- **越权面**：三条路由全部经 `Depends(get_current_user_id)`，无匿名可达路径；无 `user_id` 可注入点。
- **向量泄露**：router 白名单重建，实测报文无 embedding；`store.list_facts` 的向量不外传。
- **表结构**：本次**未新增/修改任何表或迁移**（`store/db.py` 的 +18 行属上一变更）；`memories` 表与索引沿用；无破坏性迁移。
- **依赖**：`git diff requirements.txt frontend/package.json` 为空；未引入新依赖。
- **`_lock`**：`delete_session` 用内联 SQL，无重入；20 线程压力无死锁。
- **日志泄露**：记忆明文不进日志（两个文件均无 `logging/logger/print`）。
- **开发库未被污染**：全部对抗性探测运行在临时库；验证结束后实测 `data/openunknown.db` 的 `memories` 行数 = **0**、`sessions` = 8、`users` = 2，与验证前一致。

---

## 七、需人工决定的事项

1. **【阻塞·必须先修】B1**：`delete_session` 对可能不存在的 `checkpoints`/`writes` 表加 `try/except sqlite3.OperationalError`（或把记忆级联 SQL 前移），并补一条「表不存在时删会话」的回归用例。**这是本次验收标准 4 能否成立的前提。**
2. **【阻塞·需修或书面豁免】B2**：`MemorySection.tsx` 渲染 `created_at`（1 行），或人工书面追认「时间只在 API 层返回即视为达标」并同步修改 proposal 验收标准 1 的措辞。
3. **Y1 口径裁决**：`styles.css`（现 1087 行）是否受 `coding.md` §3 的 300 行约束？若受，本次 +23 行需拆分。
4. **Y3 产品决策**：「清空全部长期记忆」是否应连 `kind='summary'` 的会话摘要一并清除（或至少在 UI 说明摘要仍保留）？
5. **Y4**：是否新增 `requirements-dev.txt` 固化 `pytest`（沿用上轮未决项）？
6. **Y5**：提交时是否把 `memory-phase2` 与 `memory-manage` 拆成两个 commit，并回填真实 `git diff --stat` 与 commit hash（`feature.md` 的 commit 栏仍为空）？
7. **Y6 人工项**：请在有登录环境的浏览器中确认设置弹窗「我的记忆」的真实渲染 / 删除 / 清空 / 空态，本轮**无法自动验证**。
8. **Y9**：确认 `/badcases` 是否应为真实路由（`test_plan.md` 将其列为回归项，但前端并无该路由）。

---

## 附：本次验证执行过的命令清单（可复核）

```bash
# 只读 / 文档
cat context/rule/review.md / context/rule/coding.md / context/risk-ledger.md
cat context/version/20260919-101804-memory-manage/{proposal,feature,test_plan}.md
cat context/version/20260918-175408-memory-phase2/test_report.md
git status --short ; git diff --stat ; git diff --numstat ; git diff backend/store/sessions.py
git show HEAD:backend/store/sessions.py ; git log --oneline -3 ; git ls-files data ; cat .gitignore

# test_plan 第一节 8 条（逐条执行并记录退出码）
.venv/bin/python -c "import backend.main"
.venv/bin/python -m pytest test/test_memory.py -v         # 16 passed
.venv/bin/python -m backend.eval.prompt_eval              # 4 项全 ✓
cd frontend && npm run typecheck                          # 零输出
cd frontend && npm run build                              # ✓ built in 3.03s
.venv/bin/python - <<'PY'  # app.routes 内省：/api/memory 三条
curl -s -w '%{http_code}'  http://127.0.0.1:8000/api/memory ; .../{id} ; ...（DELETE）
wc -l <SettingsModal.tsx/MemorySection.tsx/routers/memory.py/store/memory.py> 等

# 回归
.venv/bin/python -m pytest -q                             # 16 passed, 1 warning
curl /api/runs /api/sessions /api/usage /api/settings / /traces /badcases
# 登录态回归：TestClient 遍历 /api/models /modes /sessions /runs /usage /settings /mcp/servers /files/limits ...
grep -n "Route|path=" frontend/src/App.tsx

# 对抗性验证（均内联执行，临时隔离库，未落盘脚本、未改产品代码）
T1 store.delete_fact_owned(B, A的fact) -> False，A 记忆仍在
T2 store.delete_all_facts(A) -> 1；B 不受影响
T3 HTTP B 删 A 的 fact -> 404，A 记忆仍在
T4 GET /api/memory 字段集合 + 原始报文关键词扫描；store.list_facts 对照（仍带 embedding）
T5 HTTP DELETE /api/memory 清空隔离
T6 delete_session(B,A的sid) / delete_session(A,B的sid) -> False×2，双方数据完好
T7 delete_session 级联 9 项检查（含手工插入「绑 session_id 的 fact」做对抗）
T8 _lock 同线程二次 acquire=False（不可重入证明）+ delete_session 线程 join(5) 0.10ms
T9 20 线程 create/save/add/delete/clear 混合压力
T10 边界：不存在/空(尾斜杠)/空格/SQL注入/5000字/summary id/他人 token
T11 无 token×3、POST|PUT|PATCH、伪造 token、空 Bearer
T12 响应格式与空态；DELETE /api/memory/ 重定向链与「是否会清空全部」验证
T13 query 参数篡改（?user_id=他人）与 jwt 另一密钥/alg=none 伪造
B1 全新库端到端：POST /api/chat（无 ApiKey）-> 会话入侧栏 -> DELETE /api/sessions/{id} -> 500
   + 双连接（共享连接 vs 独立 sqlite3 连接）验证半截删除与后续 commit 顺带落盘

# 收尾核对
grep -rn "created_at|createdAt" frontend/src/  # 证明记忆列表未用时间
grep -n "\.memory-" frontend/src/styles.css    # 7 个类均已定义
grep -rn "logging|logger|print(" backend/store/memory.py backend/api/routers/memory.py
grep -rn "pytest" requirements*.txt pyproject.toml setup.py setup.cfg
sqlite3 data/openunknown.db：memories/sessions/users 行数（验证前后对比，未污染）
```

> 本轮验证**未修改任何产品代码**；写入的文件仅为本 `test_report.md`。验证后 `git status` 复核仍为 15 modified + 8 untracked（与验证前一致），开发库 `memories` 行数保持 0。

---

# 修复记录（修复轮次 1）

> 修复人：写代码 agent ｜ 触发：本报告判 🔴 红（B1/B2）
> 处置依据：沿用上一变更（memory-phase2）人工裁决的先例「红 → 修」

| 项 | 问题 | 修复 |
|----|------|------|
| **B1** | 全新库删会话时 `DELETE FROM checkpoints` 抛 `no such table` → `DELETE /api/sessions/{id}` 返回 **500**，且**新增的记忆级联清理排在其后、永远执行不到**（孤儿摘要）；同时造成半截删除（行已删未 commit） | `store/sessions.py` 对 `checkpoints`/`writes` 的删除加 `try/except sqlite3.OperationalError`（与 `db.py` 既有做法一致），异常不再中断后续级联清理 |
| **B2** | `MemorySection.tsx` 只渲染 `content`，`created_at` 是死字段 → 验收标准「列出内容**+时间**」未达成 | 每条记忆渲染 `created_at`（本地化日期），配套 `.memory-time` 样式 |

## 新增回归用例

`test/test_memory.py` 13 → **17 passed**，其中：

- `test_delete_session_survives_missing_checkpoint_tables`（B1）：用**内存库**精确模拟「sessions/memories 存在、checkpoints/writes 不存在」的全新库形态，断言不抛错**且级联清理仍执行**；不触碰真实开发库。

## 突变反证（证明用例非重复断言）

用「旧逻辑」在同一形态的库上执行，实测：
```
旧实现：抛 OperationalError -> no such table: checkpoints
→ B1 场景真实；旧实现下级联清理确实被吞掉；新实现 try/except 后不再发生
```

## 修复后自测

```
.venv/bin/python -m pytest test/test_memory.py   ->  17 passed
.venv/bin/python -c "import backend.main"         ->  OK
cd frontend && npm run typecheck / npm run build  ->  均通过
行数：SettingsModal 245 / MemorySection 95 / api/routers/memory.py 48 / store/sessions.py 103（均 ≤300）
```

## 仍待人工决定（本轮未处理，见本报告第五节）

- `styles.css` **1087 行且本次 +23**：存量超限且增长，**CSS 是否受 `coding.md` §3 约束需定口径**；
- 「清空全部长期记忆」不清理会话摘要（`kind='summary'` 仍在并可注入后续对话）——与 R10 隐私语义有落差；
- 拉取失败静默降级为空态，用户可能误判「系统没记我的事」；
- `feature.md` 的 diff 数字与实测有出入（两个变更同处工作区、无 commit 边界，无法按变更拆分）；
- `pytest` 仍未写入 `requirements.txt`（沿用上轮 R6）。

## 状态

B1/B2 已修，机器项自测全绿。按 SOP 请人工裁决：是否再走一轮 3.3 复验，以及上述 5 项存疑如何处置。

---

# 复验结论（轮次 2）

> 复验人：独立验证 agent（轮次 2，未参与编码，未接受任何自述）
> 复验时间：2026-09-19 11:12:44
> 复验对象：轮次 1 修复 + 人工裁决后的补强（`git status`：17 modified + 9 untracked；`git log` 最新仍为 `723c31c`，**本轮变更依旧无 commit 边界**）
> 依据：`context/rule/review.md`、`context/rule/coding.md`、本目录 `proposal.md` / `feature.md` / `test_plan.md`（期望值 23 passed）与本报告「修复记录（修复轮次 1）」
> 方法：逐条亲自重跑；**自己写探测脚本**做对抗性验证，全部在**临时隔离库**（运行时改写 `store.db.DB_PATH` 并清空 `_conn`）或 `/tmp` 内联脚本中执行；对 R7 新用例逐一做**源码级/行为级突变反证**；对前端用 **esbuild 打包真实组件 + Node 运行时驱动 hooks** 实测渲染，而非只读代码。
> 环境：Python 3.12.13（`.venv`）、pytest 9.1.1、Node v26.5.0、FastAPI TestClient、esbuild（`frontend/node_modules/.bin/esbuild`）。

## 结论：🟡 黄

**轮次 1 的两个红灯（B1/B2）经对抗性验证确认已真实修复；`test_plan` 第一节 8 条机器项全部重跑通过；proposal 第 2 节 6 条验收标准本轮全部达成。但补强的 R7 用例中有 1 条被证明是「同义反复」，且新增测试文件触碰 `coding.md` §3 的 300 行硬约束，故不能给绿。**

| 项 | 判定 | 依据 |
|----|------|------|
| **B1**（全新库删会话 500 + 级联被吞） | ✅ **已修（对抗性证实）** | 真实全新库 HTTP 路径 **200**；级联清理执行；并用 `git show HEAD` 的旧源码做突变反证：旧逻辑必抛 `no such table: checkpoints` 且摘要成孤儿（详见第二节） |
| **B2**（记忆列表不显示时间） | ✅ **已修（运行时证实）** | 用真实组件运行时渲染出 `<span class="memory-time">2026/9/19</span>`；构建产物内亦含 `memory-time` + `.created_at*1e3`（详见第三节） |
| **补强·失败态** | ✅ 有效 | 500 / 401 均渲染 `.memory-error`「记忆加载失败，请关闭后重试」，**不再落入静默空态**（运行时实测） |
| **补强·说明文案** | ✅ 准确 | 「只包含长期事实」与 `list_facts` 的 `kind='fact'` 过滤一致；「摘要随会话删除」在 B1 修复后成立（`session_id` 传的是原始会话 id，级联 WHERE 能命中） |
| **补强·R7 用例** | ⚠️ **部分有效** | 6 条中 5 条经突变证明有效；`test_schedule_extraction_skips_when_no_api_key` **被证明是同义反复**（见第五节） |
| **约定** | ⚠️ **违反 §3** | `test/test_memory.py` **400 行 > 300**（上一轮 267）；CSS 豁免只覆盖纯样式文件，不覆盖测试文件（见第六节） |

**不是红**：无 pytest 失败、无 typecheck/build/import 失败、6 条验收标准无未达成项、关键路径均已实跑。
**不是绿**：变更点虽已覆盖，但补强宣称的 R7 覆盖存在 1 条实证无效，且新增文件违反硬约束——属 `review.md` §一「验证过了，但存在信息缺口」。

---

## 一、`test_plan` 第一节 8 条逐条重跑（真实输出 + 退出码）

| # | 命令 | 真实输出摘要 | 退出码 | 通过 |
|---|------|--------------|--------|------|
| 1 | `.venv/bin/python -c "import backend.main"` | 无输出（无异常） | 0 | ✅ |
| 2 | `.venv/bin/python -m pytest test/test_memory.py -v` | `collected 23 items` → **`23 passed in 0.42s`**（23 条用例名逐一列出） | 0 | ✅ |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.0.0`；身份/行为/输出格式/信息补充 4 层全 `[✓]`；`结果：全部通过` | 0 | ✅ |
| 4 | `cd frontend && npm run typecheck` | `tsc --noEmit` 零输出 | 0 | ✅ |
| 5 | `cd frontend && npm run build` | `✓ built in 3.03s`，产出 `dist/assets/index-qXBltMi7.js` (372.51 kB) / `index-*.css`；仅既有 `>500 kB` chunk 提示 | 0 | ✅ |
| 6 | 路由注册（`app.routes` 内省） | `['GET'] /api/memory`、`['DELETE'] /api/memory/{fact_id}`、`['DELETE'] /api/memory` 三条全部注册 | 0 | ✅ |
| 7 | 未登录 `curl` 三条 `/api/memory*`（对 127.0.0.1:8000 运行中实例） | `GET -> 401 {"detail":"未登录"}`、`DELETE /api/memory/whatever -> 401`、`DELETE /api/memory -> 401` | 0 | ✅ |
| 8 | 文件行数 | `SettingsModal.tsx` **245**、`MemorySection.tsx` **104**、`api/routers/memory.py` **48**（均 ≤300） | 0 | ✅（另见第六节：测试文件超限） |

**全量 pytest**：`.venv/bin/python -m pytest -q` → **`23 passed, 1 warning in 0.70s`**，退出码 0（唯一 warning 仍为第三方 `pydantic_settings`，与本变更无关）。

---

## 二、B1 对抗性复验（含突变反证）

**A. 真实全新库形态（不 monkeypatch，走真实 `get_conn()` 建库 + 真实 HTTP 路由）**

```
表存在情况: {'sessions': True, 'memories': True, 'checkpoints': False, 'writes': False}
删前 summary='该会话的滚动摘要'  facts=1
真实 HTTP DELETE /api/sessions/{id} -> 200 {"ok":true}  (3.2 ms)
级联后: session 行=0  summary 行=0  fact 行=1
独立 sqlite3 连接看 sessions 行 = 0        ← 无「半截删除」
-> PASS: 200（修复前 500），级联清理执行，跨会话 fact 保留，checkpoints 仍不存在
```

**B. 突变反证（用 `git show HEAD:backend/store/sessions.py` 的旧源码在同一形态库上执行）**

```
HEAD 版 delete_session 是否含 try/except: False
旧逻辑 delete_session -> 异常: OperationalError: no such table: checkpoints
旧逻辑下: 共享连接 session 行=0  summary 孤儿行=1  独立连接 session 行=1
-> PASS: 突变反证成立（旧逻辑必抛错、级联被吞、且半截删除）
```

结论：`try/except sqlite3.OperationalError` 的修复真实生效，且**新的级联 DELETE 不再被前置异常吞掉**；B1 的三个后果（500 / 孤儿摘要 / 半截删除）均已消除。用例 `test_delete_session_survives_missing_checkpoint_tables` 与真实行为一致。
> 一处低危观察（非阻塞）：`except sqlite3.OperationalError` 较宽，若真发生 `database is locked`，也会被静默吞掉并跳过 checkpoint 清理（共享单连接 + `_lock` 串行下概率很低）。与 `db.py:57-64` 既有写法一致，沿用可接受。

---

## 三、B2 对抗性复验（运行时渲染，非只读代码）

用 esbuild 打包**真实的 `MemorySection.tsx`**（把 `react` / `react/jsx-runtime` 别名为自写 hooks 替身），在 Node 中驱动 `useEffect`/`useState` 并序列化真实元素树：

```
--- 成功且有 1 条记忆 ---
<div class="memory-box">…<span class="memory-title">我的记忆（1）</span>…
  <div class="memory-item"><span class="memory-text">用户在北京</span>
  <span class="memory-time">2026/9/19</span>
  <button class="btn-icon del" title="删除这条记忆">删除</button></div>…
--- open=false 时 fetch 调用次数 = 0（期望 0）---
```

- `created_at`（`1789787497`）被渲染为本地化日期 `2026/9/19`，位于 `memories.map` 内 → **不是死字段**；
- 构建产物交叉印证：`dist/assets/index-qXBltMi7.js` 内含 `className:"memory-time",children:new Date(a.created_at*1e3).toLocaleDateString()`；
- `types.ts:215-219` `MemoryFact.created_at: number` 存在，typecheck 通过。
> 仍无法自动验证的是浏览器内的最终视觉/交互（人工项），但「是否渲染了时间」已被运行时证据确证。

---

## 四、补强项验证

### 4.1 拉取失败 → 显式错误提示（运行时实测）

先用真实打包的 `endpoints.ts` 验证失败**必然 reject**（否则 `catch` 不会触发）：

```
[PASS] 500 -> reject: ApiError(500) boom
[PASS] 401 -> reject: ApiError(401) 登录已过期，请重新登录
[PASS] 200 -> resolve facts=1 total=1 created_at=1
请求: ["DELETE /api/memory/mem-a%2Fb%20c","DELETE /api/memory"]   ← 路径已正确转义
```

再用第三节的运行时渲染实测四个状态：

| 场景 | 渲染结果 | 判定 |
|------|----------|------|
| 成功 1 条 | `我的记忆（1）` + `memory-text` + `memory-time` | ✅ |
| 成功但空 | `memory-empty`「系统还没有为你保存任何长期记忆」 | ✅ 空态 |
| **500 失败** | `memory-error`「记忆加载失败，请关闭后重试」 | ✅ **显式错误，非空态** |
| **401 未登录** | `memory-error`「记忆加载失败，请关闭后重试」 | ✅ 显式错误 |

`styles.css:1078` `.memory-error` 已定义（`color: var(--red)`）。→ 补强目标达成，轮次 1 的 **Y2 已闭合**。

### 4.2 说明文案准确性

- 「这里只包含『长期事实』」→ `store.list_facts` 的 SQL 为 `WHERE user_id = ? AND kind = KIND_FACT`，`summary` 不会出现在列表中，**准确**；
- 「各会话的对话摘要随该会话一起删除（在左侧会话列表删除即可）」→ 在 B1 修复后成立；且已核对 `graph.py:162/197` 传给记忆层的 `session_id` 是**原始会话 id**（非 `thread_id`），与 `delete_session` 级联 WHERE 的 `session_id = ?` 一致，**能命中**；
- 清空确认框「清空后系统将不再记得你的偏好与长期事实」→ 与 `delete_all_facts` 只删 `kind='fact'` 一致，**准确**（不再过度承诺）。

### 4.3 R7 用例有效性审查（逐条突变反证）

| 用例 | 突变 | 结果 | 判定 |
|------|------|------|------|
| `test_extract_facts_parses_and_stores` | `memory.add_fact` → no-op | 用例 **FAIL**（AssertionError） | ✅ 对「入库失效」敏感，非同义反复 |
| `test_extract_facts_skips_similar_existing_fact` | `FACT_DEDUP_SIM = 1.1`（去重永不触发） | 用例 **FAIL** | ✅ 对去重阈值敏感 |
| `test_extract_facts_swallows_llm_error` | 源码级把 `except Exception` 改成 `except ZeroDivisionError` | 突变体**抛出** `RuntimeError: model down` | ✅ 能捕获「不再吞异常」的回归；但**无正向断言**，对 no-op 实现也会通过（弱，可接受） |
| `test_evict_overflow_keeps_newest` | ① `_evict_overflow` → no-op ② 改成「留最旧删最新」 | ① **FAIL** ② **FAIL**（集合断言不匹配） | ✅✅ 对「是否裁剪」与「裁剪方向」都敏感，**强有效** |
| `test_schedule_extraction_without_loop_is_noop` | — | 基线 PASS；`-W error::RuntimeWarning` 下 6 条 R7 用例全过（无「未 await 协程」告警） | ✅ 有效但天然较弱（仅断言不抛错） |
| **`test_schedule_extraction_skips_when_no_api_key`** | **源码级删除 `if not api_key` 守卫**，再把测试模块的 `memory` 指向突变体 | **用例仍然 PASS** ← 同义反复 | ⚠️ **无效** |

**同义反复的根因（实证）**：`schedule_extraction` 的守卫顺序是「先查 `api_key`（209-210 行）→ 再 `asyncio.get_running_loop()`（212 行）」。而 pytest 同步上下文**没有运行中的事件循环**，所以即便删掉 `api_key` 守卫，函数也会在 `get_running_loop()` 处 `RuntimeError` 提前返回，`_background` 依旧为空——用例断言的 `len(_background) == before` 与守卫**无关**：

```
去掉 api_key 守卫后，同步上下文调用：_background 0 -> 0
突变体（无 api_key 守卫）下 test_schedule_extraction_skips_when_no_api_key -> PASS
真实实现（有事件循环时）：_background 0 -> 1（仅合法调用创建任务）
```

→ 该用例的 docstring 声称覆盖「无 ApiKey 或空回答时直接跳过」，**但 api_key 守卫实际零覆盖**；要真正覆盖必须在 `asyncio.run(...)` 内调用。轮次 1 修复记录/`test_plan` 第 2 条对「R7 已补齐」的表述需按此修正。

---

## 五、回归复验（隔离库 + TestClient 真实路由）

**越权 / 隔离 / 向量泄露**

| 检查 | 实测 | 判定 |
|------|------|------|
| A 的 token `GET /api/memory` | `200 {"facts":[{"id","content":"A-秘密","created_at"}],"total":1}`，字段集合与 `{id,content,created_at}` **严格相等** | ✅ |
| 泄露关键词扫描（`embedding` / 向量字面量） | 命中 **0**；同时 `store.list_facts(A)[0]` **确实含 embedding** → 证明是 router 白名单真剥离 | ✅ |
| B 删 A 的记忆 | `404 {"detail":"记忆不存在或无权访问"}`，A 记忆仍在 | ✅ |
| A `DELETE /api/memory?user_id=B` | `200 {"ok":true,"deleted":1}`，A=0 / B=1 → query 参数被忽略 | ✅ |
| A 删自己的 summary 行 id | `404`，摘要仍在（`kind` 过滤生效） | ✅ |
| 伪造 token | `401` | ✅ |

**既有接口形状未变**：`/api/models` `/api/modes` `/api/sessions` `/api/runs` `/api/usage` `/api/settings` `/api/mcp/servers` `/api/files/limits` 全 **200**；`/api/runs/{不存在}`、`/api/sessions/{不存在}/messages`、`/api/nope` 全 **404**；`/api/runs`（未登录）**401**。
**SPA**：`/`、`/traces`、`/badcases` 均 `200 text/html`（`/badcases` 仍由 `path="*"` 兜底，属既有行为）。
**锁/并发**：20 线程混合 `create_session / save_summary / add_fact / delete_session / delete_all_facts` → 完成 **20/20**、异常 `[]`、无死锁（修复在 `_lock` 内仍是内联 SQL，无重入）。
**`coding.md` CSS 豁免与现状一致性**：`git diff context/rule/coding.md` 确认新增豁免条款；`styles.css` 实测 1089 行且 `grep -c "function|=>|const |import "` = **0**（纯样式），豁免与其「纯样式文件」表述**一致**。`test_plan` 第 8 条要求的三个文件均 ≤300。**已知豁免，不重复上报。**

**开发库未被污染**：复验前后 `data/openunknown.db` → `memories=0 / sessions=8 / users=2`（与轮次 1 一致）；全部探测均在临时库。

---

## 六、本轮新发现（非轮次 1 已列项）

| ID | 问题 | 级别 | 证据 / 影响 |
|----|------|------|-------------|
| **N1** | **`test/test_memory.py` 400 行 > 300，违反 `coding.md` §3**（上一轮 267 行；本轮 R7 补强使其越限） | 🟡 | `wc -l test/test_memory.py = 400`。人工豁免只写「**纯样式文件**（如 `styles.css`）」，不覆盖测试文件；红线标准未含行数，故记黄。建议按测试主题拆分（如 `test_memory_recall.py` / `test_memory_store.py`） |
| **N2** | **`test_schedule_extraction_skips_when_no_api_key` 是同义反复**，`schedule_extraction` 的 `api_key` 守卫实际零覆盖 | 🟡 | 见第四节 4.3 的源码级突变：删掉守卫后用例仍 PASS。需在 `asyncio.run()` 内补真实覆盖 |
| **N3** | `delete_session` 的 `except sqlite3.OperationalError` 过宽，会连带吞掉 `database is locked`，静默跳过 checkpoint 清理 | ⚪ 提示 | 与 `db.py` 既有写法一致；共享单连接 + `_lock` 下概率低，非阻塞 |
| **N4** | `feature.md` 内部数字自相矛盾且已过期：第 29 行写「13 → **16 passed**」、第 39 行写「13 → **17 passed**」，而 `test_plan` 与实测均为 **23**；`MemorySection.tsx` 写「92 行」，实际 **104** | ⚪ 提示（文档） | `feature.md` 未随补强同步更新 |
| **N5** | proposal §4 承诺的 `store/memory.py::delete_summaries_for_session` **未实现**（改为在 `delete_session` 内联 SQL），`store/__init__.py` 无该导出 | ⚪ 提示（与 proposal 偏差，但功能等价） | `grep -rn delete_summaries_for_session backend/` → 无命中 |
| **N6** | `MemorySection.tsx:12` 注释仍称「SettingsModal 已超 300 行」，实际 245 行（轮次 1 的 Y7 未修） | ⚪ 提示 | 注释不准确 |
| **N7** | 单条删除/清空失败仍 `catch {}` 静默（轮次 1 Y10 未变） | ⚪ 提示（UX，非补强范围） | `MemorySection.tsx:43/55`；补强只处理了「列表拉取」失败态 |

**轮次 1 已闭合项**：B1 ✅、B2 ✅、Y2（失败态静默）✅。
**沿用未决（不重复计数）**：`styles.css` 豁免（人工已裁定）、`pytest` 未入 `requirements.txt`、跨变更待办已记 `context/backlog.md`；Y3/Y5/Y9 及人工项仍待人工裁决。

---

## 七、需人工决定（本轮新增/更新）

1. **N2（建议修）**：把 `schedule_extraction` 的 `api_key`/空回答守卫用例改到 `asyncio.run()` 内断言，使其对守卫突变敏感；否则「R7 已补齐」不成立。
2. **N1（建议修或裁定）**：`test/test_memory.py` 400 行越限——拆分或书面裁定测试文件是否豁免 §3。
3. **N4（建议顺手修）**：同步 `feature.md` 的 passed 数字与行数，避免文档再次自相矛盾。
4. 轮次 1 遗留仍需裁决：Y3（清空是否连摘要一起清）、Y5（两变更拆 commit + 回填 `git diff --stat`/hash）、Y6（浏览器人工项）、Y9（`/badcases` 期望值）。

---

## 附：本轮复验执行过的命令/脚本（可复核，均未修改产品代码）

```bash
# 文档
cat context/rule/review.md context/rule/coding.md \
    context/version/20260919-101804-memory-manage/{proposal,feature,test_plan,test_report}.md
wc -l backend/store/sessions.py backend/store/memory.py backend/api/routers/memory.py \
      frontend/src/components/{MemorySection,SettingsModal}.tsx frontend/src/styles.css test/test_memory.py
git status --short ; git diff context/rule/coding.md ; git show HEAD:backend/store/sessions.py

# test_plan 第一节 8 条（逐条执行并记录退出码）
.venv/bin/python -c "import backend.main"                 # exit 0
.venv/bin/python -m pytest test/test_memory.py -v         # 23 passed
.venv/bin/python -m backend.eval.prompt_eval              # 4 项全 ✓
cd frontend && npm run typecheck && npm run build         # 零输出 / ✓ built in 3.03s
.venv/bin/python - <<'PY'  # app.routes 内省 /api/memory 三条
curl -s -w '%{http_code}' -X GET|DELETE 127.0.0.1:8000/api/memory[...]   # 401 ×3

# B1 对抗性（临时隔离库 + TestClient 真实路由 + HEAD 旧源码突变）
B1-A 全新库 HTTP DELETE /api/sessions/{id} -> 200，级联执行，fact 保留，独立连接无半截
B1-B exec(git show HEAD:...sessions.py) 旧 delete_session -> OperationalError + summary 孤儿

# B2 对抗性（esbuild 打包真实组件 + Node hooks 驱动 + 元素树序列化）
esbuild src/components/MemorySection.tsx --alias:react=<shim>  -> 运行四态渲染
grep -o '.\{120\}created_at\*1e3.\{120\}' frontend/dist/assets/index-*.js

# 补强验证
esbuild src/api/endpoints.ts -> Node 实测 fetchMemories 在 500/401 时 reject
R7 突变反证：add_fact=no-op / FACT_DEDUP_SIM=1.1 / _evict_overflow=no-op|留最旧 /
             schedule 守卫源码级删除 / extract_facts except 定向替换
.venv/bin/python -m pytest -q -W error::RuntimeWarning -k "schedule or evict or extract"   # 6 passed

# 回归
.venv/bin/python - <<'PY'  # 越权/隔离/?user_id 篡改/summary id/伪造 token + 8 个既有接口 + 3 个 SPA
.venv/bin/python - <<'PY'  # 20 线程混合并发（无死锁）
sqlite3 data/openunknown.db（只读）memories/sessions/users/runs 行数（复验前后一致）
```

> 本轮复验**未修改任何产品代码**；写入的文件仅为本 `test_report.md`（追加本节）。`git status` 复核与复验前一致。

---

# 修复记录（修复轮次 2）

> 修复人：写代码 agent ｜ 触发：复验（轮次 2）判 🟡 黄，其中 N1/N2 属确定性缺陷

| 项 | 问题 | 修复 |
|----|------|------|
| **N2** | `test_schedule_extraction_skips_when_no_api_key` 是**同义反复**：守卫排在 `get_running_loop()` 之前，同步 pytest 上下文本就提前返回，删掉守卫用例仍 PASS → 守卫零覆盖 | 断言移入 `asyncio.run()`（事件循环内），使「有无守卫」产生可观测差异 |
| **N1** | `test/test_memory.py` **400 行 > 300**，违反 `coding.md` §3（人工豁免仅覆盖纯样式文件） | 拆出 `test/test_memory_manage.py`（R10-A + R7 部分）；现 `test_memory.py` 211 行 / `test_memory_manage.py` 223 行 |
| ⚪ | `except sqlite3.OperationalError` 偏宽，会连带吞掉 `database is locked` | 收窄为「只吞 `no such table`」，其它 OperationalError 照常上抛 |
| ⚪ | `feature.md` 数字过期/自相矛盾；`MemorySection.tsx` 注释称 SettingsModal 超 300（实际 245） | 均已订正；`test_plan.md` 期望值同步更新 |

## N2 突变反证（证明修复后的用例有效）

```
删掉 memory.py 的 `if not api_key or not answer.strip(): return` 守卫
  → pytest 退出码 1（1 failed）  ✅ 用例捕获到守卫缺失
还原后 → 23 passed
```

## 修复后自测

```
.venv/bin/python -m pytest test/ -q          ->  23 passed
.venv/bin/python -c "import backend.main"     ->  OK
cd frontend && npm run typecheck / npm run build -> 均通过
行数：test_memory.py 211 / test_memory_manage.py 223 / MemorySection.tsx 104 / SettingsModal.tsx 245（均 ≤300）
```

## 本轮未处理（沿用人工裁定 / 已记录）

- `styles.css` 300 行限制 → 人工裁定**豁免**，已写入 `coding.md` §3；
- `pytest` 未入 `requirements.txt`、召回阈值未校准、断连丢尾部抽取 → 已记入 `context/backlog.md`；
- 删除/清空失败仍为静默 `catch {}`（未影响可用性，暂记 backlog 观察）；
- 前端真实交互（列表渲染、删除、清空、失败态）属人工项。

## 状态

N1/N2 与两处 ⚪ 已处理，机器项自测全绿。请人工裁决：是否再走一轮复验，或直接进入提交与台账回填。



---

# 复验结论（轮次 3 · 最终）

> 复验人：独立验证 agent（未参与编码，未修改任何产品代码）
> 复验时间：2026-09-20
> 复验对象：合并为一个版本目录后的最终工作区（`git status` 19 modified + 9 untracked；无 commit hash）
> 依据：`context/rule/review.md`、`context/rule/coding.md`、本目录 `feature.md` / `test_report.md`（历史）+ 本轮焦点 6 项（R5 移除合并 / 记忆·用量独立入口 / `App/` 成包 / `SettingsModal` 回落 / `test/memory/` / `version` 合并为 2 目录）

## 结论：🟢 绿

**机器可查 7 项全绿（23 passed / import / prompt_eval / typecheck / build / 服务启动 + 401/200）；本轮 6 处未经独立验证的改动逐条复核全部正确；R5（上一轮判黄的首要原因）已实证关闭且 `【推理生成】` 标注清零。** 残留项均为已记 `context/backlog.md` 的已知项或纯人工目视项，不构成黄灯。

- **本轮 6 处新改动**（R5 移除合并 / 记忆·用量迁出为左下角独立入口 / `App/` 成包 / `SettingsModal` 回落 / 测试移入 `test/memory/` / `version` 合并）全部通过机器验证与结构自洽检查。
- **上轮遗留的黄灯主因 R5**：`merge_system_messages` 已删除（backend 无残留命中），`graph.py:217` 直接 `llm.ainvoke(messages)` 原样发送，`【推理生成】` 标注在 backend/frontend/test 源码全部清零。
- 已知项（`pytest` 未入 requirements、阈值未校准、RAG 评测集放宽、断连丢抽取、超 300 行存量 6 个）均已在 `context/backlog.md`，本轮不重复上报、不阻塞。

## 一、机器验证（test_plan 第一节，逐条亲自执行）

| # | 命令 | 真实输出 | 退出码 | 通过 |
|---|------|---------|--------|------|
| 1 | `.venv/bin/python -m pytest test/ -q` | `23 passed, 1 warning in 0.72s`（唯一 warning 为第三方 pydantic_settings，与本变更无关） | 0 | ✅ |
| 2 | `.venv/bin/python -c "import backend.main"` | `IMPORT OK` | 0 | ✅ |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | `prompt 版本：1.0.0`，身份/行为/输出格式/信息补充 4 层全 `[✓]`，`结果：全部通过` | 0 | ✅ |
| 4 | `cd frontend && npm run typecheck` | `tsc --noEmit` 零输出 | 0 | ✅ |
| 5 | `cd frontend && npm run build` | `✓ built in 3.15s`，产出 `dist/assets/index-DVVlmnIM.js` (376 kB) 等（仅既有 >500kB chunk 提示，非错误） | 0 | ✅ |
| 6 | uvicorn 127.0.0.1:8125 启动 + curl | `GET /api/memory` → **401** `{"detail":"未登录"}`；`GET /api/runs` → **401**；`GET /` → **200** text/html；`GET /traces` → **200** text/html；日志 `Application startup complete`（验后 kill） | 0 | ✅ |

> 测试收集核实：23 条用例全部来自 `test/memory/`（`test_memory.py` 13 + `test_memory_manage.py` 10）；`test/test_mcp_server.py` 是测试用的 MCP 计算器服务（0 条 `def test_`），不参与收集。

## 二、本轮 6 处新改动的结构自洽检查（自己读代码 + typecheck/build）

### 1. `App/` 包拆分 import 正确 ✅
- `main.tsx:3` `import App from "./App"` → 解析到 `App/index.tsx`（含 `export default function App`）；typecheck + build 双过，证明解析成立。
- `App/index.tsx` 引 `./AppHeader`（第 34 行）与 `./Modals`（第 39 行），两子组件均为纯展示、props 齐全；`git status` 显示旧 `App.tsx` 已删除（`D frontend/src/App.tsx`），源码无 `App.tsx` 残留引用。

### 2. Sidebar 5 入口 props 与状态灯 ✅
- Sidebar 现为 5 个入口按钮：模型设置（`status-dot` 绑定 `hasApiKey`）、用量统计（`status-dot` 绑定 `usageCount>0`）、我的记忆（`status-dot` 绑定 `memoryCount>0`）、Trace 轨迹、MCP 扩展管理。
- `App/index.tsx:234-235` 正确传入 `memoryCount={memoryCount}`、`usageCount={usageCount}`；状态灯条件为 `> 0` 点亮（`Sidebar.tsx:125/149`），与 feature.md「记忆条数>0 / 调用次数>0 点亮」一致。

### 3. `refreshCounts` 闭环 ✅
调用点三处闭环：
1. 登录后：`App/index.tsx:117` `void refreshCounts()`；
2. 对话结束：`App/index.tsx:267-270` `onSettled` → `refreshSessions()` + `refreshCounts()`；`ChatView.tsx:397` 在每轮 settle 后 `onSettledRef.current?.()` 调用；
3. 两个弹窗回传：`MemoryModal.onChanged` → `setMemoryCount(n)`、`UsageModal.onChanged` → `setUsageCount(n)`。

删除/清空记忆后状态灯会更新：`MemoryModal.handleDelete` → `onChanged(next.length)`、`handleClear` → `onChanged(0)`，经 `setMemoryCount` 驱动 Sidebar 状态灯熄灭。

### 4. 弹窗 onChanged 回传值 ✅
- `MemoryModal`：加载成功回传 `d.total`（条数）；单删回传 `next.length`；清空回传 `0`。与 `fetchMemories()` 返回 `{facts, total}` 形状一致（`endpoints.ts:245-247`）。
- `UsageModal`：加载成功回传 `u.totals.requests`（请求数）。与 `UsageStats.totals: UsageTotals { requests }` 一致（`types.ts:77-93`）。

### 5. `.mcp-label` 居中 + 图标靠左 + `.status-dot` 语义统一 ✅
- `styles.css:88` `.mcp-entry-btn.centered > .mcp-label { flex: 1; text-align: center; }`；`.mcp-icon` 靠左（`display:inline-flex`，第 89 行）。新入口「用量统计」「我的记忆」均带 `centered` + `mcp-label`。
- `grep settings-status-dot` 前端全量无遗留，统一为 `.status-dot`（`styles.css:777/781`，`.status-dot.on` 用 `var(--green)`）。

### 6. 旧结构零残留 ✅
`MemorySection`（旧组件）、`components/Settings/`（回落前的包）、`test/test_memory*.py`（平铺测试）在源码中均无残留引用；`SettingsModal.tsx` 回落为单文件 200 行，并保留「用量统计/我的记忆已移到左侧栏底部独立入口」说明文案。

## 三、R5 移除合并核查 ✅

| 项 | 结果 |
|----|------|
| `grep merge_system_messages`（backend/test/frontend） | **无命中**（仅历史 `test_report.md` 文档内出现） |
| `graph.py` 发送方式 | 第 217 行 `response = await llm.ainvoke(messages)`，直接原样发送 `assemble_model_messages` 返回的 messages；第 188-191 行注释明确「实测支持多条/任意位置 system，直接原样发送、trace 记录真实报文、不做合并（保真）」 |
| `【推理生成】` 标注 | backend/frontend/test 源码**全部清零**（全量 grep 仅命中 AGENTS.md / rule / version 文档） |
| `context.py` | `assemble_model_messages` 直接返回 `[system, system(kind=memory), ...history]`，无合并逻辑；207 行 ≤300 |

## 四、目录合规核查 ✅

- `context/version/` 现仅 **2 个目录**：`20260918-130821-trace-panel`、`20260918-175408-memory-phase2`（符合「从 6 合并为 2」）。
- 本变更目录恰好 **4 份文档**：`proposal.md` / `feature.md` / `test_plan.md` / `test_report.md`，无 `proposal_xxx.md` 之类并列后缀。
- `coding.md` §6 文本（「一个提交对应一个变更目录」+「目录内固定 4 份文档」）与实际一致。

## 五、行数合规 ✅

超 300 行文件共 **6 个**，全部为存量、行数与 `backlog.md` 记录完全一致：

| 文件 | 当前行数 | 相对 HEAD | 判定 |
|------|---------|-----------|------|
| `frontend/src/components/ChatView.tsx` | 939 | 未改动 | 存量，未增长 |
| `frontend/src/components/McpModal.tsx` | 513 | 未改动 | 存量，未增长 |
| `frontend/src/components/Markdown.tsx` | 445 | 未改动 | 存量，未增长 |
| `backend/api/streaming.py` | 356 | +24/-99（431→356，下降） | 未增长 |
| `backend/agent/graph.py` | 343 | +27/-115（431→343，下降） | 未增长 |
| `backend/agent/tools/browser_use.py` | 334 | 未改动 | 存量，未增长 |

新增文件全部 ≤300：`App/index.tsx 297`、`AppHeader 81`、`Modals 72`、`MemoryModal 132`、`UsageModal 121`、`SettingsModal 200`、`Sidebar 187`、`endpoints.ts 259`、`types.ts 219`、`test_memory.py 211`、`test_memory_manage.py 223`、`context.py 207`、`memory.py 218`。

## 六、仍未通过 / 存疑项（均非机器可验项，交人工或已记 backlog）

1. **浏览器目视**（Sidebar 5 入口渲染、状态灯实际点亮/熄灭、两个新弹窗的交互）：无浏览器自动化，属人工项；本轮只确认代码结构与 typecheck/build 正确。
2. **长对话摘要质量、偏好召回是否真正改变回答**：需真实 ApiKey + 真实长对话，人工项。
3. **已知项（已在 `context/backlog.md`，本轮不重复上报）**：`pytest` 未入 `requirements.txt`、召回/去重阈值未校准、RAG 评测集放宽、断连丢尾部抽取、超 300 行存量文件 6 个。

## 附：本轮执行过的命令清单（可复核）

```
git status --short ; git log --oneline -5
ls context/version/ ; ls context/version/20260918-175408-memory-phase2/
find frontend/src -type f ; find test -type f
.venv/bin/python -m pytest test/ -q                    # 23 passed
.venv/bin/python -c "import backend.main"              # IMPORT OK
.venv/bin/python -m backend.eval.prompt_eval           # 全部通过
cd frontend && npm run typecheck && npm run build      # 零输出 / ✓ built in 3.15s
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8125 + curl（/api/memory 401、/api/runs 401、/ 200、/traces 200）（验后 kill）
grep -rn merge_system_messages backend/ test/ frontend/src/   # 无命中（源码）
grep -rn 推理生成 backend/ test/ frontend/src/                # 无命中（源码）
grep -rn settings-status-dot frontend/ ; grep -rn MemorySection frontend/src/   # 无命中
find（frontend/src、backend、test）超 300 行文件清单
git diff --numstat HEAD -- graph.py streaming.py       # 存量超限未增长
.venv/bin/python -m pytest test/memory/ --collect-only -q   # 23 tests collected
```

> 本轮复验**未修改任何产品代码**；写入的文件仅为本节追加的 `test_report.md`。
