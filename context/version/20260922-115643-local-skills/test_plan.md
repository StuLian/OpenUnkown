# 测试计划 · 20260922-115643-local-skills（批次 A + 批次 B 合并）

> 供独立验证 agent 执行。机器可查项优先，人工判断/安全审查项单独列出。

## 一、机器可查（必须全绿）

| # | 命令 | 期望 |
|---|------|------|
| 1 | `.venv/bin/python -c "import backend.main; import backend.agent.graph"` | 无异常 |
| 2 | `.venv/bin/python -m pytest test/skills/ -q` | **11 passed** |
| 3 | `.venv/bin/python -m pytest test/shell/ -q` | **11 passed** |
| 4 | `.venv/bin/python -m pytest test/ -q` | **45 passed**（全量无回归） |
| 5 | `.venv/bin/python -m backend.eval.prompt_eval` | 4 项全 ✓ |
| 6 | `cd frontend && npm run typecheck` | 无 TS 报错 |
| 7 | `cd frontend && npm run build` | 构建成功 |
| 8 | grep 无残留：`LARK_SECTION` / `load_skill_descriptions` / `include_lark` / `lark_write_confirmation` / `_FEISHU_KWS` | 0 命中 |
| 9 | `.venv/bin/python -c "from backend.agent.tools import TOOLS; print([t.name for t in TOOLS])"` | 含 `run_command`、不含 `lark_cli` |
| 10 | `.venv/bin/python -c "from backend.agent.skills import get_skill_directory; print(len(get_skill_directory().splitlines()))"` | 30 行，含非 lark skill |

## 二、边界与安全（重点审查）

| # | 检查点 | 关注 |
|---|--------|------|
| 1 | **read_skill 路径穿越** | `../`、绝对路径、`~`、符号链接逃逸是否全被拒（`resolve_within` 包含性校验） |
| 2 | **run_command 任意命令执行面** | 写/未知命令是否必经 interrupt 确认；**shell 运算符/重定向是否一律判 write（防 `ls --help && rm` 绕过）** |
| 3 | **风险分级默认拒绝** | 非只读白名单命令兜底 write；白名单是否误放行危险命令 |
| 4 | **环境变量泄露** | `env` 是否已移出白名单；`_run_shell` 是否传 `_minimal_env()`（不透传 ApiKey/Token） |
| 5 | **lark-cli 分级等价迁移** | 前缀剥离后走 `classify_risk`；`high-risk-write` 确认后 `ensure_yes` 补 `--yes` |
| 6 | **超时/截断/cwd/降级** | `_run_shell` timeout + `_truncate` + 固定 cwd；扫描/读取失败「跳过+告警」不崩 |
| 7 | **不回归** | `/api/chat/confirm` 协议不变；飞书写操作等价确认；天气/酒店/浏览/MCP 不受影响 |
| 8 | **文件行数** | 新增/改动文件均 ≤300 行 |

## 三、验收标准对照（proposal 批次 A + B 第 2 节）

| 验收项 | 可验证方式 | 状态 |
|--------|-----------|------|
| 扫描解析全部 skill（含非 lark） | 机器 #10 | ✅ |
| skill 目录注入 system prompt | 代码审查 + 功能自检 | ✅ |
| read_skill 拉正文/references | 单测（解析/剥离）+ 人工（真实模型） | 部分覆盖 |
| read_skill 路径安全 | 单测（4 条）+ 人工审查 | ✅ |
| run_command 执行 + 超时/截断/降级 | 单测（`_truncate`）+ 功能自检 | ✅ |
| 风险分级读放行/写确认/未知兜底 | 单测（test_shell.py） | ✅ |
| shell 运算符防绕过 | 单测 + 功能复测 | ✅ |
| lark 提示词注入全移除 | 机器 #8 | ✅ |
| lark_cli 工具退役 | 机器 #9 | ✅ |
| 确认卡片通用化 | 前端 build + 代码审查 | ✅ |
| ≥1 pytest | 机器 #2/#3 | ✅ |
| 安全人工审查 | 人工审查（§二） | 待审 |

## 四、已知无法自动验证项（需人带 ApiKey 手工验）

- 真实对话「读飞书文档」→ `read_skill("lark-doc")` → `run_command("lark-cli docs +fetch ...")` 走通；
- 飞书/通用**写操作**是否弹通用确认卡片、确认后执行、取消不执行；
- 「AI 日报」类 skill 经 `read_skill` 拉正文 + references 走通；
- `npx skills find ...` 真实跑通（需本机 npx + 网络）；
- 白名单在真实使用中的误放行/误拦截表现。
