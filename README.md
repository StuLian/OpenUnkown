# OpenUnknown

基于 FastAPI + LangGraph 的多模型问答应用。

- 需要**登录**（本地账号密码 + 开放注册，JWT 会话）。
- 登录后在「模型设置」里填写**模型服务 ApiKey**（默认**百炼 / DashScope**），
  未配置 ApiKey 的用户**无法使用对话功能**（无任何兜底）。
- ApiKey **加密存储**（Fernet 信封加密），明文不落库、不回显。

## 前端（React + TypeScript + Vite）

前端源码位于 `frontend/`，构建产物 `frontend/dist/` 由 FastAPI 直接托管，
服务器无需安装 Node。`dist/` **不入库**，由 `deploy/deploy_local.sh` 在本地构建后随部署包上传。

### 一键启动开发环境（推荐）

```bash
./dev.sh
```

同时拉起后端 `uvicorn --reload`（`127.0.0.1:8000`）与前端 Vite HMR（`http://localhost:5173`，
`/api` 自动代理到后端），浏览器访问 `http://localhost:5173`。改 Python 代码后端自动重载、
改 React 代码前端即时热更新；首次运行自动创建 `.venv` 并安装前后端依赖，`Ctrl+C` 一键全停。

### 手动分步

```bash
cd frontend
npm install                 # 首次
npm run build               # 构建到 frontend/dist（本地跑 uvicorn 前需先构建）
npm run dev                 # 仅前端（/api 代理到 127.0.0.1:8000，热更新）
npm run typecheck           # 类型检查
```

> 本地直接 `uvicorn backend.main:app` 前，需先执行 `npm run build` 生成 `frontend/dist/`；
> 线上部署则由 `deploy/deploy_local.sh` 自动完成前端构建。

## 接入 LangSmith 追踪

本项目基于 LangGraph，接入 LangSmith **无需任何埋点代码**——只要配置好环境变量，
所有 agent 执行、LLM 调用、工具调用都会自动上报到 LangSmith。

### 1. 准备 API Key

1. 登录 [LangSmith](https://smith.langchain.com/)（SaaS 云端）；
2. 在 Settings → API Keys 里创建一个 Key（形如 `lsv2_pt_...`）。

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 Key：

```dotenv
LANGSMITH_API_KEY=lsv2_pt_你的真实Key
LANGSMITH_TRACING=true
```

> 可选配置：
> - `LANGSMITH_PROJECT`：trace 写入的项目名，默认使用应用名 `OpenUnknown`；
> - `LANGSMITH_ENDPOINT`：仅**自托管** LangSmith 需要，SaaS 云端无需设置。

应用启动时会自动读取项目根目录的 `.env`（`backend/config.py` 中加载），
无需手动 `export`。

### 3. 安装依赖

`langsmith` 与 `python-dotenv` 已加入 `requirements.txt`：

```bash
pip install -r requirements.txt
```

### 4. 启动并验证

```bash
uvicorn backend.main:app --reload
```

发起一次对话后，打开 [LangSmith](https://smith.langchain.com/)，
在项目 `OpenUnknown`（或你自定义的项目名）下即可看到对应的 trace。

每次请求还会附带以下元信息，方便在控制台检索与过滤：

- `tags`：`openunknown`、`model:<模型>`、`mode:<模式>`
- `metadata`：`session_id`、`model`、`mode`

### 环境变量说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `LANGSMITH_API_KEY` | 是 | LangSmith API Key（`lsv2_pt_...`） |
| `LANGSMITH_TRACING` | 是 | 设为 `true` 开启自动追踪 |
| `LANGSMITH_PROJECT` | 否 | 项目名，默认 `OpenUnknown` |
| `LANGSMITH_ENDPOINT` | 否 | 自托管地址，SaaS 不需要 |

> 说明：模型服务 ApiKey **不再通过环境变量或本地文件兜底**，而是登录后按用户在界面填写。

## 登录与 ApiKey 配置

### 1. 登录 / 注册

打开应用后先注册或登录（本地账号密码）。登录后签发 JWT 会话令牌，前端保存在
`localStorage`，后续请求通过 `Authorization: Bearer <token>` 携带。

### 2. 填写模型服务 ApiKey（默认百炼）

登录后点击左下角「模型设置」：

1. 选择平台（当前仅「百炼 / 阿里云 DashScope」，数据结构已为多平台预留）；
2. 填入 ApiKey（形如 `sk-...`），可先「测试连接」验证；
3. 保存后**立即生效**，无需重启。

### 3. 加密存储与无兜底

- ApiKey 用 **Fernet** 对称加密后存入 `data/openunknown.db` 的 `user_api_keys` 表，
  明文不落库、不回显；解密所需的 DEK 用服务端主密钥包裹后存入 `users.dek_ciphertext`
  （信封加密），服务重启后可恢复，**无需重新登录**；
- 未配置 ApiKey 的用户在界面上会被拦截、无法发送消息；后端也会在 `/api/chat`
  直接返回错误事件，**不做任何环境变量 / 本地文件兜底**（开发阶段同样必须填写）。

> 平台扩展：在 `backend/config.py` 的 `PLATFORMS` 里新增条目即可接入其他平台。
