# 跨变更待办 / 已知问题

> 记录**不属于任何单个变更**、但已知需要处理的问题。append-only，处理后标注「已解决」并保留行。
> 每个变更自身的风险走 `risk-ledger.md` 与对应 `version/`。

| 日期 | 来源 | 问题 | 建议处置 | 状态 |
|------|------|------|---------|------|
| 2026-09-19 | `20260918-175408-memory-phase2` 验证实录 | RAG 评测集 `recall@5=0.311 / MRR=0.620 / nDCG@5=0.377`，4/16 全未命中。根因**不全是检索差，而是宽泛属性类 query 的 golden 标注过窄**：如「太空针塔附近可以看塔景」golden 只标 3 家，实际返回的 Travelodge / Mediterranean Inn / Executive Inn By The Space Needle 就在塔旁却被判 miss；「带餐厅」语料 56 家有餐厅、golden 只标 4 家 | 单开变更：① 对宽泛属性类 query 放宽 golden（或改写 query 使其可判定）；② 复核 recall/MRR/nDCG 阈值口径；③ 重跑取得新基线 | 待处理 |
| 2026-09-19 | `20260918-175408-memory-phase2` 验证 | `pytest` 已装 `.venv` 但**未写入 `requirements.txt`**，仓库无 dev 依赖文件 → 他人按 README 装完跑不了 `test/test_memory.py` | 决定是否新增 `requirements-dev.txt`（或 `requirements.txt` 内注释行） | 待处理 |
| 2026-09-19 | `20260918-175408-memory-phase2` 验证 | 记忆召回阈值 `MEMORY_MIN_SIM=0.35`、去重阈值 `FACT_DEDUP_SIM=0.92` 均为**未经真实数据校准**的保守默认 | 积累真实记忆数据后跑一轮校准（可复用 `eval/` 框架） | 待处理 |
| 2026-09-19 | `20260918-175408-memory-phase2` 验证 | 客户端中途断开时 `_stream_turn` 在 `yield` 处被关闭，尾部 trace 落库与长记忆抽取均被跳过（**既有行为**，非本次引入） | 如需保证抽取覆盖率，可改为在 `finally` 中触发或加补偿任务 | 待处理 |
| 2026-09-20 | `20260918-175408-memory-phase2` 合规审计 | **超 300 行代码文件（存量）**：`ChatView.tsx 939`、`McpModal.tsx 513`、`Markdown.tsx 445`、`api/streaming.py 356`、`agent/graph.py 343`、`tools/browser_use.py 334`（`App.tsx 303` 已于同变更拆为 `App/{index.tsx,AppHeader.tsx,Modals.tsx}` 解决） | 按 `coding.md` §3 新规（拆分须成包）逐个拆成同名目录包；建议单开变更、按文件分批做 | 待处理 |
| 2026-09-20 | 同上 | **「平铺拆分」违规**：`components/SettingsModal.tsx`+`MemorySection.tsx` 应改为 `components/Settings/{index.tsx,MemorySection.tsx}`；`test/test_memory*.py` 应改为 `test/memory/` | 已完成回改 | **已解决**（见 `20260918-175408-memory-phase2/feature.md`） |
