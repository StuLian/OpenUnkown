# feature · 20260918-175408-memory-phase2（一版合并）

> 状态：已实施（待收尾）
> 关联 proposal：本目录 `proposal.md`（Phase 2 记忆系统）+ `proposal_memory_manage.md`（R10-A 记忆入口）
> 合并说明：本目录最初只记录 Phase 2 记忆系统；后在**同一个未提交工作区**内持续迭代，按
>   `coding.md` §6「一个提交对应一个变更目录」合并了以下原独立目录的改动与记录：
>   - `20260919-101804-memory-manage`（记忆查看/删除入口，Phase 2 验证发现的 R10 落地）——文档移入本目录（`*_memory_manage.md`）
>   - `20260920-173940-coding-split-rule`（coding.md「拆分必须成包」规则）——并入本文
>   - `20260920-174637-split-into-packages`（平铺拆分回改为包）——并入本文
>   - `20260920-193807-memory-entry`（记忆/用量独立入口 + 状态灯）——并入本文

## 一、长期记忆系统（token 预算 + 滚动摘要 + 可检索长记忆）
- 后端：`agent/memory.py`（编排：预算判断 / 滚动摘要 / 事实抽取 / 向量召回，阈值常量集中于此）、
  `agent/context.py`（上下文组装 + 记忆注入 + 历史压缩）、`store/memory.py`（memories 表存取）、
  `store/db.py`（新增 memories 表，幂等迁移）
- 记忆是独立 `kind="memory"` 的 SystemMessage，trace 里以 `memory` tag 展示；注入时自动打 `memory_injected` flag
- **实测**（真实 ApiKey，遍历全部在册模型 + 多位置）：DashScope 支持多条/任意位置 system，故**不做合并**、原样发送（trace 即真实报文）

## 二、记忆的查看/删除入口（R10-A）
- 后端：`api/routers/memory.py`（`GET /api/memory` 列表 / `DELETE /api/memory/{id}` 单条 / `DELETE /api/memory` 清空，均按 user 隔离、越权 404、不泄露 embedding）
- `store/sessions.py`：`delete_session` 增加**级联清理该会话摘要**（只清 summary，跨会话 fact 保留；只吞 `no such table`）
- 前端：`components/MemoryModal.tsx` 独立弹窗（列表 / 单条删除 / 清空全部 / 空态 / 失败态）

## 三、用量统计独立入口
- 前端：`components/UsageModal.tsx`（总计 + 按模型 + 按日期，比原设置内嵌多了按日表）

## 四、工程规范与结构
- `coding.md` §3 新增「**拆分必须成包**」+ §6 新增「**一个提交对应一个变更目录**」；纯样式文件豁免 300 行
- 结构回改：`test/memory/`（测试成包）；`components/Settings/` 回落为平铺 `SettingsModal.tsx`（单文件不需包）
- `src/App/` 成包（`index.tsx` + `AppHeader.tsx` + `Modals.tsx`），解决 App.tsx 存量超限
- Sidebar 入口（5 个）：MCP 扩展管理 / Trace 轨迹 / 我的记忆 / 用量统计 / 模型设置；
  新入口图标靠左、标题居中，均带状态灯（`.status-dot`，记忆条数 > 0 / 调用次数 > 0 点亮）

## 五、验证与修复汇总（独立验证共抓出 9 个真问题，均已修复）

| 变更 | 验证结论 | 发现并修复 |
|------|---------|-----------|
| Phase 2 记忆系统 | 🔴→🟡 | R1 召回失败逃逸 / R2 base64 进预算 / R3 空摘要伪造落库 / R4·N1 事实数字被篡改 / R8 未 await 协程 / N3 文档过期 / N4 孤儿数据 |
| 记忆入口（R10-A） | 🔴→🟡 | B1 全新库删会话 500 / B2 时间字段死代码 / N2 同义反复用例 |

- 另有 R5（多条 system 兼容性）经真实 API 实测**排除**（详见 `test_report.md` 修复轮次 3）

## 测试
- `test/memory/test_memory.py`（211 行）+ `test/memory/test_memory_manage.py`（223 行）：**23 passed**
- 覆盖：预算判断 / 事实解析 / 摘要组装 / 历史压缩 / 存储闭环 / 召回排序与阈值 / 越权删除 / 清空隔离 /
  删会话级联 / B1 全新库形态 / extract_facts 全链路 / 相似去重 / 失败降级 / 上限淘汰 / 调度守卫

## 验证（机器可查，全绿）
```
.venv/bin/python -m pytest test/ -q       ->  23 passed
.venv/bin/python -c "import backend.main"  ->  OK
.venv/bin/python -m backend.eval.prompt_eval ->  全部通过
cd frontend && npm run typecheck / build   ->  通过
行数：App/index 297 / AppHeader 81 / Modals 72 / SettingsModal 200 / MemoryModal 132 / UsageModal 121 / Sidebar 187（均 ≤300）
```

## 未处理（已记 `context/backlog.md`）
- 超 300 行存量文件 6 个（`ChatView 939` / `McpModal 513` / `Markdown 445` / `streaming.py 356` / `graph.py 343` / `browser_use.py 334`）
- `pytest` 未入 `requirements.txt`；召回/去重阈值未校准；RAG 评测集放宽；断连丢尾部抽取
- `agent/context.py` / `api/messages.py` 是否收进包（待人工定性）

## commit
- hash：（待人提交后回填）
