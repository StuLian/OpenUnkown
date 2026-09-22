# feature · 20260922-115643-local-skills（本地 skill：读取 + 执行，两批次合并）

> 状态：已实施（待收尾）
> 关联 proposal：本目录 `proposal.md`（批次 A 只读最小版 + 批次 B 通用执行工具）
> 合并说明（2026-09-22）：按 `coding.md` §6 合并两个连续批次到本目录（原 `20260922-132227-generic-executor` 并入）。

## 一、批次 A · 本地 skill 读取（`backend/agent/skills/`，4 文件均 ≤300 行）

- `registry.py`：`parse_frontmatter`/`strip_frontmatter`（手写解析 name/description，支持单行 + `>`/`|` 块标量，不引 PyYAML）、
  `scan_skills(dir)`、`build_directory(index)`、`get_skill_index()`/`get_skill_directory()`（目录指纹 + `threading.Lock` 缓存）。
- `loader.py`：`resolve_within`（路径安全，`resolve()` 后必须仍在 root 内）、`load_skill_doc`、`load_skill_ref`（先快速拒绝越界 ref_path）。
- `reader.py`：`@tool read_skill(skill_name, ref_path="")`，只读。
- `config.py` 新增 `SKILLS_DIR`（默认 `~/.agents/skills/`）；`prompts.py` 新增 `SKILLS_DIRECTORY_SECTION`；
  `graph.py` `_get_system_prompt` 常驻注入目录、`read_skill` 常驻绑定。
- 实测：30 个 skill 全部扫出（含 ai-daily-report / archify / find-skills）。

## 二、批次 B · 受控通用执行工具 + 移除 lark 提示词注入

- 新增 `tools/shell.py`：`run_command` @tool（`/bin/sh -c` 执行，`_TIMEOUT=60`、`_MAX_OUTPUT=20000`、固定 cwd、`_minimal_env`）；
  `classify_command_risk`（lark-cli 前缀委托 `classify_risk`；其余走只读白名单 + 默认拒绝；**shell 运算符/重定向一律 write**）。
- `tools/lark_cli.py` 裁剪为风险分级工具（保留 `classify_risk`/`ensure_yes`/`_run`，删 `lark_cli` @tool / `load_skill_descriptions` / `is_available`）。
- `tools/__init__.py`：`TOOLS` 增 `run_command`、去 `lark_cli`。
- `prompts.py` 删 `LARK_SECTION`；`router.py` 删 `_FEISHU_KWS`/feishu 锚点。
- `graph.py`：闸门「工具名==lark_cli」→「工具名==run_command」，interrupt type `command_write_confirmation`；
  `run_command`+`read_skill` 常驻绑定；`_get_system_prompt` 去 lark。
- `api/streaming.py` 匹配 `command_write_confirmation`；`schemas.py`/`chat.py`/前端 `ChatView.tsx` 文案通用化。
- 前端确认卡片按 DeepSeek Harness 审批面板重做样式（样式微调，无逻辑改动）：顶部警示条（圆点 + 「等待确认」/「高危操作，等待确认」）+
  正文（标题 + 等宽命令）+ 右对齐按钮（取消 / 确认执行）；`styles.css` 新增 `--warn` 变量。

## 三、测试

- `test/skills/test_skills.py`（11 条）：frontmatter 解析/正文剥离/目录扫描/`../`+绝对路径+符号链接逃逸拒绝/块标量解析。
- `test/shell/test_shell.py`（11 条）：只读白名单/`--help` 只读/未知默认写/shell 运算符强制写/env 不放行/最小化 env 脱敏/`_truncate`/`ensure_yes`。
- 全量 `pytest test/`：**45 passed**（skills 11 + shell 11 + 存量 23）。

## 四、验证（机器可查，全绿）

```
.venv/bin/python -c "import backend.main / backend.agent.graph"  ->  OK
.venv/bin/python -m pytest test/ -q                              ->  45 passed, 1 warning（pydantic 存量告警）
.venv/bin/python -m backend.eval.prompt_eval                     ->  全部通过
cd frontend && npm run typecheck                                 ->  通过
cd frontend && npm run build                                     ->  ✓ built
功能自检：classify_command_risk(ls)=read / (npx)=write / (rm)=write / (ls --help && rm)=write / (env)=write；
          run_command('echo')='hello-world'；system prompt 无 lark 注入、含 skill 目录；
          run_command + read_skill 常驻绑定
```

## 五、安全修复（独立验证抓出 2 个红级，已修，见 test_report.md §⑦）

1. 命令风险分级可被 shell 运算符绕过（`ls --help && rm` 被判 read）→ 新增 `_has_shell_meta` 前置检查；
2. `env` 命令泄露环境变量 → `env` 移出白名单 + `_run_shell` 传 `_minimal_env()`。

## 六、未处理（已记 `context/backlog.md`）

- skill 语义召回自动匹配 + 正文自动注入；目录 token 校准；lark 目录去重；
- run_command v1 无 OS 沙箱（container/seccomp）；只读白名单未经真实命令集校准。

## 七、文档与规则（零档，随本 commit 记录，不单开 version）

- `AGENTS.md`：§3 模块职责（`skills/` + `run_command`）、§6 #6/#7（通用命令执行约定）、§8 文件清单（自动生成，含 shell.py）。
- `context/rule/coding.md` §6：标题改为「一个可独立交付的功能批次对应一个变更目录」+ 新增「version 三档判据」表（纯规则修订，git 即记录）。
- `context/backlog.md`：新增 5 条待办（语义召回自动匹配 / lark 目录去重 / PyYAML / OS 沙箱 / 白名单校准）。

## commit

- hash：`9ce31ab962d21aa8e7faf207dc4ed8430e1df978`（短 `9ce31ab`）
