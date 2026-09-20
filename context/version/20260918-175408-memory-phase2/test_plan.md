# 测试计划 · 20260918-175408-memory-phase2

> 供独立验证 agent 执行。机器可查项优先，人工判断项单独列出。

## 一、机器可查（必须全绿）

| # | 命令 | 期望 |
|---|------|------|
| 1 | `.venv/bin/python -c "import backend.main"` | 无异常 |
| 2 | `.venv/bin/python -m pytest test/test_memory.py -v` | **14 passed**（修复轮次 1 后由 9 增至 14，含 R1–R4/N1 回归） |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | 4 项全 ✓，退出码 0 |
| 4 | `cd frontend && npm run typecheck` | 无 TS 报错 |
| 5 | `cd frontend && npm run build` | 构建成功 |
| 6 | `PRAGMA table_info(memories)` | 含 id/user_id/session_id/kind/content/embedding/created_at/updated_at |
| 7 | 服务启动 + `curl /api/runs` | 200/401（路由未破坏） |

## 二、边界与安全（人工/补充审查）

| # | 检查点 | 关注 |
|---|--------|------|
| 1 | 记忆按 user 隔离 | `list_facts/load_summary` 是否只按 user_id 过滤；跨用户是否可见 |
| 2 | 失败降级 | 摘要/召回/抽取任一步抛错时，主流程是否仍正常回答（不应 500） |
| 3 | 异步任务 | `schedule_extraction` 的 fire-and-forget 是否有未捕获异常、是否阻塞响应 |
| 4 | checkpoint 不被改 | 记忆只进 LLM 输入，是否误写 checkpoint（应无） |
| 5 | 迁移幂等 | 重复启动（已有 memories 表）不报错 |
| 6 | 文件行数 | graph.py 343 / streaming.py 356 / context.py 229 / memory.py 215 / messages.py 122（相对 HEAD 均未增长） |

## 三、验收标准对照（proposal 第 2 节）

| 验收项 | 可验证方式 | 状态 |
|--------|-----------|------|
| 长对话超预算走摘要 | 需真实 ApiKey + 长对话（人工） | 待人工 |
| 偏好被召回并影响回答 | 需真实 ApiKey（人工） | 待人工 |
| 失败降级不阻塞 | 代码审查 + 单测（召回失败返回空已覆盖） | 部分覆盖 |
| checkpoint 不变 | 代码审查（未写 checkpoint） | 待审 |
| memories 迁移幂等 | 机器可查（#6） | ✅ |
| ≥1 条 pytest | 机器可查（#2） | ✅ |
| memory tag 展示 | 需前端实际渲染（人工） | 待人工 |
| memory_injected 可筛选 | 需实际产生记忆（人工） | 待人工 |

## 四、已知无法自动验证项（需人带 ApiKey 手工验）

- 滚动摘要质量、长记忆召回是否真的改变回答、memory tag/memory_injected 的实际展示效果。
  这三项依赖真实模型调用与真实对话，属 proposal 第 7 节「人工判断」范畴。

---

# 测试计划 · 20260919-101804-memory-manage

> 供独立验证 agent 执行。

## 一、机器可查（必须全绿）

| # | 命令 | 期望 |
|---|------|------|
| 1 | `.venv/bin/python -c "import backend.main"` | 无异常 |
| 2 | `.venv/bin/python -m pytest test/ -v` | **23 passed**（`test/memory/test_memory.py` 211 行 + `test/memory/test_memory_manage.py` 223 行） |
| 2b | `.venv/bin/python -m pytest test/ -q` | 23 passed（全量） |
| 3 | `.venv/bin/python -m backend.eval.prompt_eval` | 4 项全 ✓ |
| 4 | `cd frontend && npm run typecheck` | 无 TS 报错 |
| 5 | `cd frontend && npm run build` | 构建成功 |
| 6 | 路由注册 | `/api/memory` 有 GET / DELETE / DELETE{id} 三条 |
| 7 | 未登录 curl 三条 `/api/memory*` | 均 401（鉴权生效） |
| 8 | 文件行数 | `Settings/index.tsx` 245 / `Settings/MemorySection.tsx` 104 / `api/routers/memory.py` 48 / `test/memory/test_memory.py` 211 / `test/memory/test_memory_manage.py` 223（均 ≤300；`styles.css` 经人工裁定豁免） |

## 二、边界与安全（重点）

| # | 检查点 | 关注 |
|---|--------|------|
| 1 | **越权删除** | `delete_fact_owned` 是否把 `user_id` 写进 WHERE；A 删 B 的记忆是否被拒（404/False） |
| 2 | **清空隔离** | `delete_all_facts` 是否只清本人，不误删他人 |
| 3 | **不泄露向量** | `GET /api/memory` 响应是否**不含 embedding** 字段 |
| 4 | **级联清理** | 删会话是否清掉该会话 summary，且**不**误删跨会话 fact |
| 5 | **并发/锁** | `delete_session` 内联 SQL 是否避开 `_lock` 重入死锁（该函数已持锁） |
| 6 | **空态** | 记忆为空时前端是否给出明确提示（非空白/报错） |
| 7 | **不回归** | `/api/runs`、`/traces`、`/`、`/badcases` 是否仍正常 |

## 三、验收标准对照（proposal 第 2 节）

| 验收项 | 可验证方式 |
|--------|-----------|
| 列表可看（内容+时间，无向量） | 机器：curl/读取代码；前端渲染需人工 |
| 单条删除 / 一键清空 | 单测 + 联调 |
| 严格 user 隔离、越权 404 | 单测（已覆盖） |
| 删会话级联清摘要、不留孤儿 | 单测（已覆盖） |
| 空态提示 | 人工 |
| ≥1 条 pytest | 机器（16 passed） |

## 四、人工项（需真实环境/登录）

- 设置弹窗打开后「我的记忆」列表的真实渲染、删除与清空的实际交互、空态展示效果。
