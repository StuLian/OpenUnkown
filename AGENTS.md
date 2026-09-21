# AGENTS.md — OpenUnknown 项目上下文（给 AI 看）

> 本文件是给 AI 的「项目地图」：新会话开始先读本文件即可快速上手，不必重新逐个探索目录。
> 最后更新：2026-09-19（结构有变时**务必同步更新本文件**，尤其是模块职责、命令、约定三节）。

## 1. 一句话概述

OpenUnknown：**FastAPI + LangGraph** 的多模型问答应用，前端 **React + TypeScript + Vite**。
用户登录（本地账号 + JWT）后自行填写模型服务 ApiKey（默认百炼/DashScope），ApiKey 加密落库、
**无任何环境变量/本地文件兜底**。数据存 SQLite（`data/openunknown.db`）。

## 2. 技术栈

- 后端：Python 3.10+，FastAPI，LangGraph（`langgraph` + `langgraph-checkpoint-sqlite`），LangChain，DashScope（OpenAI 兼容）
- 前端：React 18 + TypeScript + Vite（无 UI 框架，手写组件）
- 存储：SQLite（WAL），checkpoint 由 `SqliteSaver` 自行建表
- 加密：Fernet 信封加密（`cryptography`），JWT（`PyJWT`）
- 检索：FAISS + BM25（酒店 RAG）
- 追踪：LangSmith（仅环境变量，无埋点代码）

关键依赖版本（自动生成，勿手改）：

<!-- AUTO-GEN:DEPS -->
**后端（`requirements.txt`）**：

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
langgraph==0.2.60
langgraph-checkpoint>=2.0.4,<3.0.0
langgraph-checkpoint-sqlite>=2.0.0,<3.0.0
langchain-core==0.3.28
langchain-openai==0.2.14
langsmith==0.2.11
python-dotenv==1.2.3
dashscope==1.20.14
faiss-cpu>=1.8.0
numpy>=1.25
aiosqlite==0.20.0
pydantic==2.10.4
mcp>=1.0.0
cryptography>=42.0.0
PyJWT>=2.8.0
python-multipart==0.0.32
pypdf>=4.0.0
python-docx>=1.1.0
openpyxl>=3.1.0
Pillow>=10.0
```

**前端 dependencies**：mermaid ^11.17.2, react ^18.3.1, react-dom ^18.3.1, react-markdown ^10.1.0, react-router-dom ^6.30.6, remark-breaks ^4.0.0, remark-gfm ^4.0.1
**前端 devDependencies**：@types/react ^18.3.12, @types/react-dom ^18.3.1, @vitejs/plugin-react ^4.3.4, typescript ^5.6.3, vite ^5.4.11
<!-- /AUTO-GEN:DEPS -->

## 3. 模块职责（语义速览）

> 具体有哪些文件见第 8 节自动生成的清单；本节只讲各模块「是干嘛的」。

**后端 `backend/`**
- `main.py` — FastAPI 入口：组装应用、挂载静态资源、注册路由
- `config.py` — 全局配置：`PLATFORMS`、`AVAILABLE_MODELS`、`MODES`、`.env` 加载（须最先 import）
- `api/` — HTTP 层：路由（`routers/`）、请求体模型（`schemas.py`）、流式逻辑（`streaming.py`）
- `agent/` — LangGraph 智能体：状态图（`graph.py`）、LLM 封装（`llm.py`）、prompt（`prompts.py`）、**记忆编排（`memory.py`）与上下文组装（`context.py`）**、意图路由（`router.py`：关键词快速通道 + embedding 语义召回兜底）、MCP（`mcp/`）、工具（`tools/`：weather / hotels / browser_use / lark_cli）
- `auth/` — 登录 / JWT / 依赖注入（`deps.py`）
- `security/` — 加密：Fernet（`crypto.py`）、主密钥（`master_key.py`）、challenge
- `store/` — SQLite 存取：`db.py`（连接与建表）+ 各领域 store（sessions / mcp / users / usage / runs / feedback / memory）
- `rag/` — 酒店 RAG：loader / index / bm25 / embeddings / rerank / location
- `files/` — 附件解析（图片/文档）与上传
- `tracing/` — trace 采集：`collector.py`（`TraceCollector` 在一轮对话中收集原始报文/工具调用/召回，供落库与 Trace 轨迹复盘）
- `eval/` — 离线评测：`metrics.py`（recall@k/MRR/nDCG）、`rag_eval.py`（RAG 评测）、`prompt_eval.py`（prompt 结构回归）+ `datasets/`（评测集）

**前端 `frontend/`**
- `src/` — React 组件（`components/`）、认证上下文（`context/`）、api client / sse / crypto / storage（`lib/`、`api/`）、类型（`types.ts`）
- `dist/` — 构建产物（**不入库**，见第 6 节第 1 条）
- `index.html` / `vite.config.ts` / `tsconfig.json` — Vite 与 TS 配置

**顶层**
- `deploy/` — 部署脚本 + nginx + systemd + 证书（详见 `DEPLOY_ALIYUN.md`）
<!-- AUTO-GEN:LATEST -->
- `docs/` — 架构图版本演进记录，**最新 = V1.8.0**（其余为历史版本）
<!-- /AUTO-GEN:LATEST -->
- `data/` — `openunknown.db`（+ WAL/shm）、密钥文件、hotels 数据
- `csv/` — `Seattle_Hotels.csv`（RAG 数据源）
- `test/` — `test_mcp_server.py`
- `context/` — AI 协作纪律体系：`rule/`（编码约束 / 评审标准 / 收尾 SOP / 模板）+ `version/`（每次变更记录）+ `risk-ledger.md`（风险台账），详见第 6 节第 10 条
- `dev.sh` — 一键开发环境（后端 reload + 前端 HMR）
- `README.md` — 给人看的使用/部署文档

## 4. 常用命令

```bash
./dev.sh                        # 一键起前后端（推荐开发入口）：后端 127.0.0.1:8000 reload，前端 5173 HMR
OPEN_BROWSER=0 ./dev.sh         # 不自动开浏览器

# 后端
.venv/bin/uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
.venv/bin/pip install -r requirements.txt   # 装后端依赖（dev.sh 首次自动建 .venv）

# 前端（在 frontend/ 下）
npm install && npm run build    # 构建到 frontend/dist（直接跑 uvicorn 前必须先 build）
npm run dev                     # 仅前端，/api 代理到 8000
npm run typecheck               # 类型检查

# 离线评测（RAG 评测需 ApiKey；prompt 检查免费）
.venv/bin/python -m backend.eval.prompt_eval                 # prompt 结构回归检查
EVAL_API_KEY=<key> .venv/bin/python -m backend.eval.rag_eval # RAG 检索评测（recall@k/MRR/nDCG）
```

## 5. 后端 API 路由表（自动生成，勿手改）

<!-- AUTO-GEN:ROUTES -->
| 前缀 | 方法 | 路径 | 文件 |
|------|------|------|------|
| `/api/auth` | GET | `/challenge` | auth.py |
| `/api/auth` | POST | `/register` | auth.py |
| `/api/auth` | POST | `/login` | auth.py |
| `/api/auth` | GET | `/me` | auth.py |
| `/api/auth` | POST | `/logout` | auth.py |
| `/api` | POST | `/chat` | chat.py |
| `/api` | POST | `/chat/confirm` | chat.py |
| `/api` | GET | `/models` | chat.py |
| `/api` | GET | `/modes` | chat.py |
| `/api/files` | GET | `/limits` | files.py |
| `/api/files` | POST | `(空)` | files.py |
| `/api/files` | POST | `/url` | files.py |
| `/api/mcp` | GET | `/servers` | mcp.py |
| `/api/mcp` | POST | `/servers` | mcp.py |
| `/api/mcp` | DELETE | `/servers/{server_id}` | mcp.py |
| `/api/mcp` | PATCH | `/servers/{server_id}/toggle` | mcp.py |
| `/api/mcp` | POST | `/test` | mcp.py |
| `/api/mcp` | POST | `/import` | mcp.py |
| `/api/memory` | GET | `(空)` | memory.py |
| `/api/memory` | DELETE | `/{fact_id}` | memory.py |
| `/api/memory` | DELETE | `(空)` | memory.py |
| `/api/runs` | GET | `(空)` | runs.py |
| `/api/runs` | GET | `/{run_id}` | runs.py |
| `/api/runs` | POST | `/{run_id}/feedback` | runs.py |
| `/api/sessions` | GET | `(空)` | sessions.py |
| `/api/sessions` | POST | `(空)` | sessions.py |
| `/api/sessions` | DELETE | `/{session_id}` | sessions.py |
| `/api/sessions` | GET | `/{session_id}/messages` | sessions.py |
| `/api/settings` | GET | `(空)` | settings.py |
| `/api/settings` | PUT | `/api-key` | settings.py |
| `/api/settings` | DELETE | `/api-key` | settings.py |
| `/api/settings` | POST | `/test` | settings.py |
| `/api/usage` | GET | `(空)` | usage.py |
<!-- /AUTO-GEN:ROUTES -->

静态资源：`/`（React 入口，未构建返回 503）、`/assets`（`frontend/dist/assets`）。

## 6. 关键约定与坑（务必遵守）

1. **`frontend/dist/` 不入库**：由 `deploy/deploy_local.sh` 本地构建后随部署包上传。本地直接跑 uvicorn 前先 `npm run build`；服务器无需 Node。
2. **模型 ApiKey 无兜底**：不读环境变量、不读本地文件。登录后用户在「模型设置」填写，Fernet 加密存 `user_api_keys` 表，DEK 用服务端主密钥包裹存 `users.dek_ciphertext`（信封加密）。未配置的用户后端 `/api/chat` 直接返回错误。
3. **`.env` 加载点在 `backend/config.py`**：`load_dotenv` 必须位于任何第三方库 import 之前（尤其 dashscope 在 import 时会固化 api_key）。新增环境变量走 `.env`（`cp .env.example .env`，`.env` 已 gitignore）。
4. **数据库**：SQLite 单例连接 + `threading.Lock` 串行访问，WAL 模式。表：`sessions`、`mcp_servers`、`users`、`user_api_keys`、`usage_log`、`runs`（每轮 trace）、`feedback`（用户反馈）、`memories`（长期记忆：`kind='summary'` 会话摘要 / `kind='fact'` 用户事实）；checkpoint 表（`checkpoints`/`writes`）由 `SqliteSaver` 自管。建表逻辑集中在 `store/db.py` 的 `get_conn()`，含幂等迁移。**注意**：`_lock` 不可重入，已持锁的函数内不要再调同样加锁的 store 函数（如 `delete_session` 内直接执行 SQL）。
5. **扩展模型平台**：在 `config.py` 的 `PLATFORMS` 加条目即可；模型/模式白名单也在 `config.py`（`AVAILABLE_MODELS`/`MODES`），前后端共用。
6. **LangGraph 结构**：`get_graph()` 构建 `StateGraph(MessagesState)`，节点 `chat` ⇄ `tools`，`START→chat`，工具调用后回到 chat。工具按需注入（weather/hotels/browser_use/lark_cli/MCP）。
7. **飞书集成**：`agent/tools/lark_cli.py` 调用 `lark-cli`，system prompt 只注入短 domain 路由表，子命令由模型 `--help` 按需拉取。**写操作安全闸门**：tools 节点用 `interrupt()` 对 `write`/`high-risk-write` 命令先暂停，前端弹确认卡片，用户点「确认执行」后经 `POST /api/chat/confirm` 恢复执行（`high-risk-write` 确认后由 `ensure_yes()` 自动补 `--yes`）；`read` 直接放行。读写判定在 `classify_risk()`，以 `lark-cli <cmd> --help` 的 `Risk:` 行为权威信号并缓存，未知兜底为写。
8. **LangSmith**：纯环境变量自动追踪，无埋点代码；tags=`openunknown`/`model:*`/`mode:*`。
9. **Trace 轨迹**：每轮对话经 `tracing/collector.py` 的 `TraceCollector`（挂在 `config.configurable["trace_collector"]`）收集原始报文/工具调用/召回，由 `streaming.py` 落 `runs` 表并自动打 flag（`tool_error`/`no_answer`/`error`/`pending_confirm`）；用户反馈落 `feedback` 表。Trace 轨迹面板后端 `api/routers/runs.py`，前端 `TracesPanel.tsx`。trace 落库失败只告警、不影响主流程。
10. **AI 开发纪律（规则路由表）**：AI 协作规则分「常驻」与「按需」两类，按动作触发读取：
    | 动作/时机 | 必读文件 | 说明 |
    |-----------|---------|------|
    | 写代码前 | `context/rule/coding.md` | 编码硬约束（架构/目录/≤300行/依据/【推理生成】标注） |
    | 产出 proposal 前 | `context/rule/proposal.md` | 写前确认单模板 |
    | 变更收尾 | `context/rule/change_sop.md` | 全流程 SOP |
    | 打灯/评审 | `context/rule/review.md` | 红黄绿判定 + 绿灯门槛 |
    | 修 bug 前 | `context/risk-ledger.md` + 对应 `version/` | 历史回溯 |
    铁律（最高优先级，任何情况下不可跳过）：
    1. 非轻量变更先出 proposal 获人确认，未获批不写代码；
    2. 修 bug 必须先做历史回溯；
    3. 写完代码必须走收尾流程（`change_sop.md`）。
    **豁免（2026-09-19 人工裁定）**：`docs/architecture_V*.html` 架构文档的生成 / 更新**不走
    proposal / 验证 / 收尾流程**——纯文档产出，直接镜像上一版结构并更新架构内容即可；但「最新版本」
    一行仍属自动生成区，需运行 `python scripts/gen_agents_doc.py` 刷新（或随 pre-commit 自动刷新）。
11. **长期记忆（Phase 2）**：`agent/memory.py` 负责编排——超 `MAX_HISTORY_CHARS`(12000) 时滚动摘要、每轮异步抽取用户事实（`qwen-turbo`）、按 query 向量召回 top-k（numpy 余弦，不引向量库）；`agent/context.py` 的 `assemble_model_messages()` 负责组装（记忆是独立 `kind="memory"` 的 SystemMessage，trace 里以 `memory` tag 展示）。**阈值常量集中在 `agent/memory.py` 顶部**。记忆只进 LLM 输入、**不写 checkpoint**；任何一步失败都降级、不阻塞主流程。用户可在**左侧栏底部「我的记忆」独立入口**查看/删除（`api/routers/memory.py`，前端 `components/MemoryModal.tsx`）；「用量统计」同为左侧栏独立入口（`components/UsageModal.tsx`）。**实测 DashScope 支持多条/任意位置 system，故不做 system 合并**（trace 即真实报文）。

## 7. 维护说明

- 第 2（依赖版本）、5（路由表）、8（文件清单）节，以及第 3 节的「最新架构文档
  版本」为自动生成区域，改代码/新增架构文档后运行 `python scripts/gen_agents_doc.py`
  一键刷新，**不要手改**。
- 已配置 pre-commit 钩子（`git config core.hooksPath .githooks`）：提交前自动刷新
  并纳入本次提交，无需手动跑生成器；跳过一次用 `git commit --no-verify`。
- 模块职责（第 3 节）与第 6 节「约定与坑」为手写区：新增/删除模块或约定时
  手动更新，并同步更新顶部日期。

## 8. 附录：源码文件清单（自动生成，勿手改）

<!-- AUTO-GEN:FILES -->
```text
backend/
  ├── agent/
  │   ├── mcp/
  │   │   ├── __init__.py
  │   │   ├── client.py
  │   │   ├── converter.py
  │   │   └── manager.py
  │   ├── tools/
  │   │   ├── __init__.py
  │   │   ├── browser_use.py
  │   │   ├── hotels.py
  │   │   ├── lark_cli.py
  │   │   └── weather.py
  │   ├── __init__.py
  │   ├── context.py
  │   ├── graph.py
  │   ├── llm.py
  │   ├── memory.py
  │   ├── prompts.py
  │   └── router.py
  ├── api/
  │   ├── routers/
  │   │   ├── __init__.py
  │   │   ├── auth.py
  │   │   ├── chat.py
  │   │   ├── files.py
  │   │   ├── mcp.py
  │   │   ├── memory.py
  │   │   ├── runs.py
  │   │   ├── sessions.py
  │   │   ├── settings.py
  │   │   └── usage.py
  │   ├── __init__.py
  │   ├── messages.py
  │   ├── schemas.py
  │   └── streaming.py
  ├── auth/
  │   ├── __init__.py
  │   ├── deps.py
  │   ├── service.py
  │   └── tokens.py
  ├── eval/
  │   ├── datasets/
  │   │   ├── prompt_cases.json
  │   │   └── rag_hotels.json
  │   ├── __init__.py
  │   ├── metrics.py
  │   ├── prompt_eval.py
  │   ├── rag_eval.py
  │   └── report.py
  ├── files/
  │   ├── __init__.py
  │   ├── image.py
  │   └── parser.py
  ├── rag/
  │   ├── __init__.py
  │   ├── bm25.py
  │   ├── embeddings.py
  │   ├── index.py
  │   ├── loader.py
  │   ├── location.py
  │   └── rerank.py
  ├── security/
  │   ├── __init__.py
  │   ├── challenge.py
  │   ├── crypto.py
  │   └── master_key.py
  ├── store/
  │   ├── __init__.py
  │   ├── db.py
  │   ├── feedback.py
  │   ├── mcp.py
  │   ├── memory.py
  │   ├── runs.py
  │   ├── sessions.py
  │   ├── usage.py
  │   └── users.py
  ├── tracing/
  │   ├── __init__.py
  │   └── collector.py
  ├── __init__.py
  ├── config.py
  └── main.py
frontend/src/
  ├── App/
  │   ├── AppHeader.tsx
  │   ├── Modals.tsx
  │   └── index.tsx
  ├── api/
  │   ├── client.ts
  │   └── endpoints.ts
  ├── components/
  │   ├── AuthOverlay.tsx
  │   ├── ChatView.tsx
  │   ├── Markdown.tsx
  │   ├── McpModal.tsx
  │   ├── MemoryModal.tsx
  │   ├── Modal.tsx
  │   ├── RunDetail.tsx
  │   ├── SettingsModal.tsx
  │   ├── Sidebar.tsx
  │   ├── TracesPanel.tsx
  │   └── UsageModal.tsx
  ├── context/
  │   └── AuthContext.tsx
  ├── lib/
  │   ├── crypto.ts
  │   ├── sse.ts
  │   └── storage.ts
  ├── main.tsx
  ├── styles.css
  └── types.ts
```
<!-- /AUTO-GEN:FILES -->
