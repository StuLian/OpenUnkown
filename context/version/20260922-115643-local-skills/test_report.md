# test_report · 20260922-115643-local-skills（批次 A + B 合并）

> 独立验证 agent 收尾验证报告（两批次合并于一个变更目录）。范围：只做验证与写报告，未改产品代码。

## ① 结论：🟡 黄（批次 B 的红级已修复，见 §⑤）

机器验证全绿、覆盖率满足绿灯门槛（逻辑有 pytest、安全有逐条人工审查）。批次 A（只读 skill 加载）直接 🟡；
批次 B（通用执行工具）独立验证曾抓出两个红级安全漏洞，实现方已修复复验，现降为 🟡。残留黄级由人裁定。

## ② 机器验证结果表（命令 → 实际结果）

| # | 命令 | 实际结果 | 退出码 |
|---|------|---------|--------|
| 1 | `import backend.main; import backend.agent.graph` | 无异常 | 0 |
| 2 | `pytest test/skills/ -q` | **11 passed** | 0 |
| 3 | `pytest test/shell/ -q` | **11 passed** | 0 |
| 4 | `pytest test/ -q` | **45 passed, 1 warning**（pydantic 存量告警，与本变更无关） | 0 |
| 5 | `python -m backend.eval.prompt_eval` | 4 项全 `[✓]`，全部通过 | 0 |
| 6 | `cd frontend && npm run typecheck` | 无 TS 报错 | 0 |
| 7 | `cd frontend && npm run build` | `✓ built`（仅 chunk 体积告警） | 0 |
| 8 | grep 残留（lark 注入相关 5 个标识符） | 0 命中 | 0 |
| 9 | `TOOLS` 列表 | 含 `run_command`、无 `lark_cli` | 0 |
| 10 | `get_skill_directory()` 行数 | 30 行，含 ai-daily-report / archify / find-skills | 0 |

## ③ 安全审查结论（逐条读源码 + 实测）

### 批次 A · read_skill 路径安全（通过）
- `loader._is_unsafe_ref` 前置拒绝 `../`、绝对路径、`~`、Windows 反斜杠，并归一后按路径节查 `..`；
- `resolve_within` 用 `Path.resolve()` 包含性校验，符号链接逃逸同样被拒（有 pytest 覆盖）；
- `read_skill` 纯只读、不解析/不执行 `metadata.requires.bins`，无新增命令执行面；
- 扫描/读取失败一律「告警 + 跳过 / 友好字符串」，主流程不崩。

### 批次 B · run_command 命令执行面（红→已修）
- 曾发现红1「shell 运算符绕过」：`ls --help && rm -rf /`、`echo x > /tmp/x` 等被判 `read` 直接执行。
  已修：`classify_command_risk` 入口 `_has_shell_meta()` 检测 `&& || ; | > < & $( 反引号 换行`，命中即 `write` 需确认。
- 曾发现红2「环境变量泄露」：`env` 在白名单 + `_run_shell` 继承完整环境 → 泄露 `LANGSMITH_API_KEY` 等。
  已修：`env` 移出白名单 + `_run_shell` 传 `_minimal_env()`（只透传 PATH/HOME/LANG/LC_*/SHELL/USER/TMP*/TERM 等）。
- 闸门迁移结构正确：`graph._tools_node` 对 run_command 的 write/high-risk-write 先 `interrupt({"type":"command_write_confirmation"})`、
  未确认不执行、`high-risk-write` 确认后 `ensure_yes` 补 `--yes`；lark 前缀正确剥离后委托 `classify_risk`。
- 执行控制通过：timeout + `_truncate` + 固定 cwd + 失败降级字符串。

## ④ 黄灯风险清单（不阻塞，人裁定）

1. **提示注入（批次 A）**：本地 SKILL.md 不可信内容进 LLM 上下文；已缓解（白名单目录 + 只读 + 不执行 requires.bins），执行面受现有工具约束。
2. **手写 frontmatter 解析（批次 A）**：只解析单行/块标量，复杂 YAML 形态降级跳过（带【推理生成】标注）。
3. **只读白名单难穷举（批次 B）**：`git`/`curl`/`find` 等不在白名单会过度确认；启发式长期存在误放行/误拦截。
4. **无 OS 沙箱（批次 B）**：v1 只靠「风险分级 + 默认拒绝 + 确认闸门 + 超时/输出上限/最小化 env」扛（带【推理生成】标注），未做 container/seccomp。
5. **run_command/read_skill 常驻绑定**：闲聊轮也带 schema；误调被「未知→写→确认」兜住，但多确认打扰。

## ⑤ 修复记录（批次 B 红级，2026-09-22）

- **红1 命令绕过**：`classify_command_risk` 加 `_has_shell_meta` 前置检查，含 shell 运算符/重定向一律 `write`。
- **红2 环境泄露**：`env` 移出 `_READ_ONLY_BINS`；`_run_shell` 加 `env=_minimal_env()`。
- 新增 4 条测试（shell 运算符强制写 / lark 带运算符强制写 / env 不放行 / 最小化 env 脱敏）。
- 复验：`pytest test/shell -q` 11 passed；`pytest test/ -q` 45 passed；功能复测确认
  `ls --help && rm`、`echo > /tmp/x`、`env`、`lark-cli ... && rm` 全判 write，`ls -la` 仍 read，`_minimal_env` 不含 `DASHSCOPE_API_KEY`。

## ⑥ 未自动验证项（需人带 ApiKey 手工验）

- 真实对话「读飞书文档」→ `read_skill("lark-doc")` → `run_command("lark-cli docs +fetch ...")` 走通；
- 写操作弹通用确认卡片、确认后执行、取消不执行；「AI 日报」skill 经 read_skill 拉正文 + references；
- `npx skills find ...` 真实跑通；白名单真实使用中的误放行/误拦截表现。
