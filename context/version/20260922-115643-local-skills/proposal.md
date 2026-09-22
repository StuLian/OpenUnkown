# 变更提案 · 本地 skill 可用（读取 + 执行，两个连续批次合并）

> 状态：已确认（两批次均获人工批准）
> 变更 ID：20260922-115643-local-skills
> 变更类型：新功能
> 分级：高风险（读取本地文件系统 + 注入不可信内容到 LLM + 开任意命令执行面 + 路径安全）
>
> **合并说明（2026-09-22）**：按 `coding.md` §6「一个提交对应一个变更目录」，本目录合并两个
> 同处一个未提交工作区、围绕同一目标（让本地 skill 可用）的连续批次——批次 A = 只读最小版
> （扫目录 + 注入目录 + `read_skill`）；批次 B = 受控通用执行工具 + 移除 lark 提示词注入。
> 原 `20260922-132227-generic-executor` 目录并入本目录。测试仍按模块分两个包（`test/skills/`、
> `test/shell/`），不合并。

---

# 批次 A · 通用本地 Skill 加载器（访问 + 按需读取，只读最小版）

> 状态：已确认（人工指令「先缩小范围，只做只读最小版」视为批准）
> 分级：高风险（读取本地文件系统 + 注入不可信内容到 LLM 上下文 + 路径安全）

## 1. 目标（一句话）
让 OpenUnknown 能**访问**用户 `~/.agents/skills/` 下的全部本地 skill（不止 lark-*，含
`ai-daily-report` / `archify` / `find-skills` 等）：把 skill 目录（name + 一句话 description）注入
system prompt，模型按需用 `read_skill` 工具读取某个 skill 的正文与 references。

## 2. 验收标准
- [ ] 扫描 `~/.agents/skills/` 能解析出全部 skill 的 `name` / `description`（含非 lark）；
- [ ] skill 目录注入 system prompt；
- [ ] 模型能 `read_skill("ai-daily-report")` 拿正文，再 `read_skill(..., ref_path="references/...")` 拉参考；
- [ ] `read_skill` 路径安全：`../`、绝对路径、`~`、符号链接逃逸一律被拒；
- [ ] 目录缺失或 SKILL.md 损坏/缺 name → 告警 + 跳过，主流程不崩；
- [ ] ≥1 条 pytest：frontmatter 解析 + 路径逃逸 + 目录扫描含非 lark。

## 3. 方案
新增 `backend/agent/skills/`（`registry` 扫描解析缓存 + `loader` 读正文/references 含路径安全 +
`reader` 提供 `read_skill`）；`graph._get_system_prompt` 注入 skill 目录，`read_skill` 常驻绑定。
零 DB / 零 API / 零前端改动；不引 PyYAML（手写解析顶层 name/description，含 `>`/`|` 块标量）。

## 4. 影响面
新增 `backend/agent/skills/{__init__,registry,loader,reader}.py`；`config.py`（`SKILLS_DIR`）；
`prompts.py`（`SKILLS_DIRECTORY_SECTION`）；`graph.py`（注入 + 绑定）；`test/skills/`；`AGENTS.md` §3。
不碰 store/DB、api 路由、router、前端、rag。

## 5. 风险
1. 提示注入（红）：不可信 SKILL.md 进 LLM 上下文；缓解=白名单目录 + 只读 + 不执行 requires.bins；
2. 路径逃逸（红）：`resolve()` 包含性校验；
3. 手写 frontmatter 解析健壮性（黄）：只解析单行/块标量，复杂 YAML 降级跳过。

---

# 批次 B · 受控通用执行工具 + 移除 lark 提示词注入

> 状态：已确认（人工「开始实现」+ 决策「退役 lark_cli 工具」）
> 分级：高风险（开任意命令执行面 + 退役已验证的 lark_cli 工具）

## 1. 目标（一句话）
新增**受控通用命令执行工具** `run_command`（沙箱化 subprocess + 风险分级 + 写操作确认闸门），让本地
skill 读完说明书后能真正执行（对齐 Claude/Codex 的通用 Bash）；同时**彻底移除 lark 提示词注入**，
lark 能力改由「skill 目录 + `read_skill` + `run_command`」承接。

## 2. 验收标准
- [ ] `run_command` 执行 shell 命令并返回输出，带超时/输出上限/降级不崩；
- [ ] 风险分级：只读直放行；写/未知默认「write」需确认；**shell 运算符/重定向（&& ; | > < & $() 反引号 换行）一律按 write 需确认**（防绕过）；
- [ ] `lark-cli` 前缀复用 `classify_risk` 的 `--help` `Risk:` 信号，`high-risk-write` 确认后 `ensure_yes` 补 `--yes`；
- [ ] 确认卡片通用化（不再写死「飞书」）；
- [ ] `LARK_SECTION` / `load_skill_descriptions` / `include_lark` 全移除；
- [ ] `lark_cli` 工具退役，lark 改由 `run_command("lark-cli ...")` 承接，写操作确认等价迁移不降级；
- [ ] ≥1 pytest；安全人工审查（默认拒绝/最小化 env/无新增绕过面）。

## 3. 方案
新增 `backend/agent/tools/shell.py`（`run_command` + `classify_command_risk` + `_run_shell` + 只读白名单 +
shell 运算符防护 + `_minimal_env`）；`lark_cli.py` 裁剪为风险分级工具（保留 `classify_risk`/`ensure_yes`，
删 `lark_cli` @tool / `load_skill_descriptions`）；`graph.py` 闸门从「lark_cli」泛化为「run_command」
（interrupt type=`command_write_confirmation`）；`prompts.py` 删 `LARK_SECTION`；`router.py` 删 feishu 死数据；
前端 `ChatView.tsx` 卡片文案通用化。

## 4. 影响面
改 `tools/shell.py`(新)、`tools/lark_cli.py`、`tools/__init__.py`、`graph.py`、`prompts.py`、`router.py`、
`api/streaming.py`、`api/schemas.py`、`api/routers/chat.py`、`frontend/ChatView.tsx`、`test/shell/`、`AGENTS.md` §3/§6。
不碰 store/DB、api 路由表（`/api/chat/confirm` 协议不变）、skills 包、rag、memory。

## 5. 风险
1. 任意命令执行（红）：靠「风险分级 + 默认拒绝 + 确认闸门 + 超时/输出上限/最小化 env」扛，v1 无 OS 沙箱（列为后续硬化）；
2. 白名单难穷举（黄）：只读白名单启发式，误放行/误拦截；
3. lark_cli 退役回归（黄）：复用 classify_risk/ensure_yes 函数本体，测试 + 真实飞书回归覆盖。
