# 变更提案 · Phase 2 记忆系统（token 预算 + 滚动摘要 + 可检索长记忆）

> 状态：待确认
> 变更 ID：20260918-175408-memory-phase2
> 变更类型：新功能
> 分级：高风险（涉及 DB 建表 + 记忆算法 + 异步任务）

## 0. 历史回溯（仅 bug 修复填写）
- 不适用（新功能，非 bug）。

## 1. 目标（一句话）
把当前「粗暴截断工具历史 + 只有 checkpoint 全量持久化」升级为三层记忆的前两层：
(1) **工作记忆**：token 预算 + 滚动摘要，长对话不再无脑截断，而是把老内容压缩成摘要；
(2) **可检索长记忆**：跨轮/跨会话记住用户事实与偏好，按当前 query 语义召回后注入。

## 2. 验收标准（怎么算「对」）
- [ ] 长对话历史超预算（约 12000 字）时，模型仍能答出早期对话的关键信息（靠摘要兜住），而不是丢失；
- [ ] 用户在某一轮说「我喜欢简洁回答」这类偏好，之后（含新会话）能被召回并影响回答；
- [ ] 摘要 / 召回 / 抽取任何一步失败时，**降级到现状**（不阻塞主流程、不报错）；
- [ ] checkpoint 原始历史**不被修改**（与现有 `_compact_history` 不改 checkpoint 的原则一致）；
- [ ] `memories` 表迁移幂等，旧库启动自动建表；
- [ ] 记忆逻辑至少有 1 条 pytest 用例（覆盖召回排序 / 预算判断 / 摘要回退之一）；
- [ ] 注入的记忆在 Trace 轨迹详情里以独立 `memory` tag 展示（与普通 `system` 区分），一眼看得出本轮注入了什么；
- [ ] 注入记忆的轮次自动打上 `memory_injected` flag，可在 Trace 轨迹面板按「注入记忆」筛选出来；

## 3. 依据（需求依据 + 技术依据）
- **需求依据**：用户原话「Phase 2 — 记忆（token 预算 + 滚动摘要 + 可检索长记忆）」。
- **技术依据（可查证）**：
  - 现状代码：`backend/agent/graph.py` 的 `_compact_history`（`_KEEP_TAIL=16` / `_OLD_TOOL_CHARS=240` 硬截断）与 `_messages_chars`（字数粗算）——本次要替换/增强的落点；
  - `backend/rag/embeddings.py` 的 `embed_texts`（DashScope text-embedding-v3，已用 query/document 两态）——长记忆向量化复用；
  - `backend/agent/llm.py` 的 `get_llm` + `backend/config.py` 的 `AVAILABLE_MODELS`（含 `qwen-turbo` 便宜模型）——摘要/抽取复用；
  - `backend/store/db.py` 单例连接 + `_lock` 串行 + 幂等迁移的既有模式——`memories` 表照此实现。
- **【推理生成】部分**：LangChain/LangGraph 的「摘要注入」与业界长记忆（MemGPT/Letta）的做法我未逐行查证源码，属通用模式推导；凡此类在实现注释中标注【推理生成】。

## 4. 方案（怎么做 + 为什么选它）
- **滚动摘要**：`_chat_node` 组装历史前，用 `_messages_chars` 粗算字数；超预算时把「保留窗口之外的老消息」连同「已有摘要」一起交给 `qwen-turbo`（便宜模型）生成新摘要，摘要作为一条 SystemMessage 注入历史开头；摘要按 `(user_id, session_id)` 存 `memories` 表滚动覆盖。**理由**：不改 checkpoint、摘要可增量滚动；**备选**：不做摘要、继续硬截断（现状）。
- **可检索长记忆**：每轮流式结束后异步（`asyncio.create_task` + try/except）调 LLM 抽取「值得长期记住的用户事实/偏好」→ 向量化存 `memories`（`kind='fact'`）；下一轮开始时用当前 query 向量做 numpy 余弦暴力召回 top-k（记忆量小，无需 FAISS），注入 system prompt 的「相关记忆」段。**理由**：复用现有 embedding，注入/召回都不阻塞主流程；**备选**：引入独立向量库（过度设计，第一版不取）。
- **注入点**：全部收敛在 `graph.py` 的 `_chat_node`（召回记忆 → 摘要压缩 → 组装 messages）。记忆注入方式：作为**独立的 SystemMessage**（带 `additional_kwargs={"kind": "memory"}`）插在基础 system 之后、history 之前，内容为「## 相关记忆」「## 历史对话摘要」两段；不放进用户消息、不做前端面板。这样 Trace 原始报文里记忆段能以独立 `memory` tag 展示（与普通 `system` 区分）。
- **模块**：`backend/store/memory.py`（存取）+ `backend/agent/memory.py`（编排：预算/摘要/抽取/召回，超 300 行则拆 `agent/memory/` 包）。
- **常量（集中在 `agent/memory.py` 顶部，一处可改）**：`MAX_HISTORY_CHARS = 12000`（摘要触发预算）、`SUMMARY_KEEP_TAIL = 16`（摘要保留的最近条数）、`MEMORY_TOP_K = 3`（召回条数）、`MEMORY_MAX_FACTS = 50`（长记忆条数上限）。
- **可观测标记**：本轮注入了记忆/摘要时，给 run 打自动 flag `memory_injected`（`TraceCollector.add_flag`），使 Trace 轨迹面板可按「注入记忆」筛选；同时在原始报文里以 `memory` tag 展示记忆段。

## 5. 影响面（改哪些 / 明确不碰哪些）
- **改**：`store/db.py`（建 `memories` 表 + 幂等迁移）、新增 `store/memory.py`、新增 `agent/memory.py`、`agent/graph.py`（`_chat_node` 注入点）、`api/streaming.py`（触发长记忆异步抽取）、`store/__init__.py`（导出）。
- **改（前端小改，为了让记忆段显示 `memory` tag 且可按记忆筛选）**：`tracing/collector.py`（序列化时读 `additional_kwargs.kind`，输出 `kind` 字段）、`frontend/src/components/RunDetail.tsx`（tag 显示 `kind ?? type`，`memory_injected` 的 flag 中文名）、`frontend/src/components/TracesPanel.tsx`（筛选下拉加「注入记忆」项）、`frontend/src/types.ts`（TraceMessage 加 `kind?`）、`frontend/src/styles.css`（memory tag 配色）。
- **明确不碰**：`router.py`（意图路由）、`rag/`（酒店检索链路）。

## 6. 风险与不确定点
1. 摘要质量：便宜模型（`qwen-turbo`）摘要可能丢关键信息 → 黄灯，缓解：摘要失败回退现状截断，后续可换更强模型；
2. 摘要同步生成会加长「超预算那一轮」的延迟 → 黄灯，缓解：异步预热作为后续优化项；
3. 异步抽取的并发/失败边界未充分验证 → 黄灯，需在收尾用真实运行 + 人工审查补验；
4. 每轮抽取/召回都调 embedding，成本上升 → 需观察，第一版不设采样；
5. 记忆膨胀（fact 无限增长）→ 第一版只加「上限 + 相似去重」的简单策略，完整治理后续再做；
6. 新逻辑暂缺自动化测试 → 按 coding.md 补 ≥1 条 pytest，收尾验收时核验；
7. 【推理生成】「多条 system 消息」在 DashScope 兼容接口是否被支持未经实测 → 实现时先验证，不支持则回退为「单条 system 拼接 + 仅 trace 侧按 kind 标记」（不改模型输入结构）。

## 7. 验证计划（预览）
- 机器可查：`import` 通过、`pytest`（记忆召回/预算判断）、前端 `typecheck`/`build`（确认零前端改动未破坏）、`memories` 表迁移幂等（老库启动 + `PRAGMA table_info`）。
- 人工判断：长对话摘要质量、偏好记忆是否真的改变回答、注入是否在 Trace 轨迹详情可见。

---

# 变更提案 · 长期记忆的查看与删除入口（R10-A）

> 状态：已确认（人工指令「选择A继续向下执行吧」视为批准）
> 变更 ID：20260919-101804-memory-manage
> 变更类型：新功能
> 分级：标准

## 1. 目标（一句话）
让用户能**看到**系统为他保存了哪些长期记忆（事实），并能**单条删除 / 一键清空**；同时修掉「删除会话不会清理该会话摘要」的级联缺口。

## 2. 验收标准
- [ ] 设置弹窗可列出当前用户的全部长期事实记忆（内容 + 时间），**不含向量**；
- [ ] 可单条删除；可一键清空（带二次确认）；
- [ ] 所有接口严格按 `user_id` 隔离，删除他人记忆返回 404（不可越权）；
- [ ] 删除会话时，该会话的滚动摘要（`kind='summary'`）被级联清理，不留孤儿；
- [ ] 记忆为空时前端有明确空态提示；
- [ ] 至少 1 条 pytest 覆盖「越权删除被拒」与「清空只清本人」。

## 3. 依据
- **需求依据**：验证报告 R10（长期记忆明文落库、用户无查看/删除入口）+ 人工裁决「选 A」。
- **技术依据**：现有模式（`api/routers/runs.py` 的 user 隔离、`store/memory.py` 读写、`SettingsModal.tsx` 的 Modal 结构、`delete_session` 的既有清理逻辑）。

## 4. 方案
- 后端新增 `api/routers/memory.py`：`GET /api/memory`（列表，剥离 embedding）、`DELETE /api/memory/{id}`（单条，带归属校验）、`DELETE /api/memory`（清空本人）；
- `store/memory.py` 增 `delete_all_facts` / `delete_fact_owned` / `delete_summaries_for_session`；
- `store/sessions.py` 的 `delete_session` 增加级联清理该会话摘要；
- 前端 `SettingsModal.tsx` 底部加「我的记忆」区块（列表 + 删除 + 清空），配套 `types.ts` / `endpoints.ts` / `styles.css`。
- **备选**：独立 `/memories` 路由页（与 Trace 面板同构）——本次不取，A 档定位是「最小可用」，设置页更贴近"隐私与数据"语义。

## 5. 影响面
- **改**：`store/memory.py`、`store/sessions.py`、`store/__init__.py`、`main.py`、新增 `api/routers/memory.py`；前端 `types.ts`、`api/endpoints.ts`、`components/SettingsModal.tsx`、`styles.css`。
- **不碰**：记忆的抽取/召回/摘要逻辑（`agent/memory.py`、`agent/context.py`）零改动；`rag/`、`router.py` 不碰。

## 6. 风险与不确定点
1. 记忆内容为**明文**返回给前端渲染（用户看自己的数据，可接受）；需确保不返回 embedding；
2. 前端在 Modal 内加载列表，弹窗打开时多一次请求 → 空态/失败态需处理；
3. 级联清理只清 summary（fact 是跨会话的，不应随会话删除）——需在代码注释写明，避免以后误改。

## 7. 验证计划
- 机器可查：`import`、`pytest`（越权/清空隔离）、`typecheck`、`build`、三条新路由经 curl 返回 401（未登录）；
- 人工：设置页打开能看到记忆列表、删除与清空生效、空态正确。
