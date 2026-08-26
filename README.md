# OpenUnknown

基于 FastAPI + LangGraph 的多模型问答应用。

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
| `DASHSCOPE_API_KEY` | 否 | 模型服务 Key（默认读 `~/.dashscope/api_key`） |
