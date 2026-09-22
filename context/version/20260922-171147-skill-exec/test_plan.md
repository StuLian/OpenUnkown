# 测试计划 · 20260922-171147-skill-exec

> 供独立验证 agent 执行。机器可查项优先，人工判断/安全审查项单独列出。

## 一、机器可查（必须全绿）

| # | 命令 | 期望 |
|---|------|------|
| 1 | `.venv/bin/python -c "import backend.main; import backend.agent.graph"` | 无异常 |
| 2 | `.venv/bin/python -c "from backend.agent.tools import TOOLS; print([t.name for t in TOOLS])"` | 含 `read_file`/`write_file`/`list_files`，含 `run_command`/`browser_search` |
| 3 | `.venv/bin/python -m pytest test/fs/ -q` | **7 passed** |
| 4 | `.venv/bin/python -m pytest test/ -q` | **52 passed**（全量无回归） |
| 5 | `.venv/bin/python -m backend.eval.prompt_eval` | 4 项全 ✓ |
| 6 | 功能自检：`read_skill.ainvoke` 返回含 `skill 目录:`；`_select_tools` 对闲聊轮也绑 7 个通用工具 | 通过 |

## 二、边界与安全（重点审查）

| # | 检查点 | 关注 |
|---|--------|------|
| 1 | **文件路径安全** | `_resolve` 的 `../`、绝对越界、符号链接逃逸是否全拒；相对路径相对项目根 |
| 2 | **写范围** | `write_file` 是否严格限定 workspace + `SKILLS_DIR` 内，能否写 `/etc` 等 |
| 3 | **write_file 免确认的边界** | 落盘不弹确认但只落两处；`run_command` 写命令确认闸门不受影响 |
| 4 | **常驻绑定不回归** | weather/hotels/MCP 仍按意图；browse 意图删除后 `_BROWSE_KWS` 无残留 |
| 5 | **skill 路径暴露** | `load_skill_doc` 返回带绝对路径，模型能否定位 scripts/ 跑渲染 |
| 6 | **文件行数** | fs.py 等新增文件 ≤300 行 |

## 三、验收标准对照（proposal 第 2 节）

| 验收项 | 可验证方式 | 状态 |
|--------|-----------|------|
| ai-daily-report 端到端跑通 | 渲染脚本实测出图 + 人工（真实模型检索→写→渲染） | 部分覆盖（渲染已实测，检索/写文件待人工） |
| 文件路径安全 | 单测（3 条越界）+ 人工审查 | ✅ |
| write_file 免确认但限 workspace | 代码审查 | ✅ |
| web/文件工具常驻、不回归 | 机器 #2/#4 + 功能自检 | ✅ |
| read_skill 带路径 | 功能自检 | ✅ |
| ≥1 pytest | 机器 #3 | ✅ |

## 四、已知无法自动验证项（需人带 ApiKey 手工验）

- 真实对话「生成今日 AI 日报」→ `read_skill("ai-daily-report")` 读说明书 → `browser_search` 检索五维度 →
  `write_file` 写 content.json → `run_command` 跑渲染 → 产出 JPG 交付用户；
- 闲聊轮 web 检索是否误触发、token 涨幅是否可接受。
