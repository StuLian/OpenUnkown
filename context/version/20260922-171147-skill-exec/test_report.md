# test_report · 20260922-171147-skill-exec（补齐 skill 执行闭环）

> 独立验证 agent 收尾验证报告。范围：只做验证与写报告，未改任何产品代码。

## ① 结论：🟡 黄（安全黄灯 #1 已修复，见 §⑦）

机器验证全绿、文件路径安全与 `run_command` 写命令确认闸门均验证通过，**无红**。原黄灯 #1（`write_file` 可写 `SKILLS_DIR` 静默覆盖 `SKILL.md` → 持久注入）与 #4（`_WORKSPACE` 漏标【推理生成】）已按人工裁决修复并复验（见 §⑦）。当前残留黄级：常驻 web 检索、skill 绝对路径进 trace。

## ② 机器验证结果表

| # | 命令 | 实际结果 | 退出码 |
|---|------|---------|--------|
| 1 | `import backend.main; import backend.agent.graph` | `import OK` | 0 |
| 2 | `TOOLS` 列表 | `['get_weather','browser_fetch','browser_search','search_hotels','run_command','read_file','write_file','list_files']`（含文件三工具 + run_command + browser_search，无 lark_cli） | 0 |
| 3 | `pytest test/fs/ -q` | **7 passed in 0.47s** | 0 |
| 4 | `pytest test/ -q` | **52 passed, 1 warning**（pydantic 存量告警，与本变更无关） | 0 |
| 5 | `python -m backend.eval.prompt_eval` | 4 项全 `[✓]`，全部通过 | 0 |

## ③ proposal vs feature 对照

| proposal §2 验收项 | 实际 | 判定 |
|---|---|---|
| fs 三工具 + 路径安全（3 类越界拒） | `tools/fs.py` `_resolve` + `test_fs.py` 7 条 | ✅ |
| write_file 免确认但限 workspace | 限 `_ALLOWED_ROOTS`（workspace + `SKILLS_DIR`） | ⚠️ 见偏差 2 |
| web/文件工具常驻、weather/map/hotel/MCP 不回归 | `_select_tools` 常驻分支 + 意图分支保留 | ✅ |
| read_skill 返回带绝对路径 | `load_skill_doc` 返回 `skill 目录: <绝对路径>` | ✅ |
| ≥1 pytest | 7 passed | ✅ |
| browse 意图删除无残留 | `router.py` grep `browse`/`_BROWSE_KWS` 零命中 | ✅ |

**偏差（均非缺陷，但需记录）**：
1. proposal §4 写「复用 `resolve_within`」，实际 `fs.py` **自实现 `_resolve`**（正偏差：自实现才支持「双根 + 相对路径相对 workspace + `expanduser`」，`loader.resolve_within` 无此语义）。
2. 验收 §2#2 措辞「读写只落在 workspace 内」，实际实现为「workspace **+ `SKILLS_DIR`**」两处（proposal §4 标题与任务描述均认可双根）。措辞比实现窄，见黄灯 1。

## ④ 安全审查结论（逐条读源码）

### a) 文件路径安全——通过
`fs._resolve`：`Path(path).expanduser()` → 相对路径拼到 `_WORKSPACE` → `resolve()`（归一 `..` + 跟随符号链接）→
遍历 `_ALLOWED_ROOTS=(_WORKSPACE, SKILLS_DIR)` 做包含性校验（`resolved == root or root in resolved.parents`）。
- `../etc/passwd` → 解析到项目根外 → 拒；
- 绝对 `/etc/pwned.txt` → 不在两根本内 → 拒；
- 符号链接指向根外 → `resolve()` 跟随后落在根外 → 拒。
三类均有 `test_fs.py` 用例覆盖，未发现绕过面。

### b) 写范围与免确认边界——通过（一处黄级残余，见⑤-1）
- `write_file` 经 `_resolve` 只能落 `workspace` + `SKILLS_DIR`，**不能写 `/etc` 或家目录其它位置**（`test_write_outside_rejected` 覆盖 `/etc` 拒绝）；
- `run_command` 写命令确认闸门**未被改动**：`graph.py` `_tools_node` 仍对 `run_command` 调 `classify_command_risk`、写/高危写 `interrupt({"type":"command_write_confirmation"})`、`ensure_yes` 补 `--yes`（第 246–283 行），文件三工具不经过该闸门（走普通 `tool.ainvoke` 分支），二者互不影响。

### c) 常驻绑定不回归——通过
`_select_tools` 的 `get_weather`/`maps_`/`search_hotels`/`_mcp_tool_hit` 意图分支全部保留；`browser_search`/`browser_fetch`/文件三工具与 `run_command`/`read_skill` 一并落入常驻分支；`router.py` 已删 `_BROWSE_KWS`/`browse` 锚点且 grep 零残留。

### d) skill 路径暴露——可接受
`load_skill_doc` 返回 `skill 目录: {entry.path.parent}\n\n{body}`，模型可据此定位 `scripts/`、写 `content.json`、跑渲染。信息泄露面 = 本地 skill 目录绝对路径（含 home 用户名）进入 LLM 上下文与 trace——单机自用、路径即用户自己的本地目录，可接受；但见黄灯 3。

## ⑤ 黄灯风险清单（不阻塞，人裁定）

1. **`write_file` 免确认 + `SKILLS_DIR` 可写根 = 可静默覆盖 `SKILL.md`（持久注入面）**：恶意/出错 skill 可让模型 `write_file` 覆写其它 skill 的说明书，因 skill 正文会经 `read_skill` 注入后续上下文，形成**跨会话持久化提示注入**。影响面：单机自用，但比「仅 workspace」多了一个可写根。建议处置：**接受继续**（对齐 Claude Code 的 write_file 免确认 + 目录白名单），后续可对「写 `SKILLS_DIR` 内 `SKILL.md`」加确认、或收紧 `write_file` 只落 workspace。
2. **常驻 web 检索（proposal #2 未排除）**：闲聊轮也带 `browser_search`/`browser_fetch` schema，模型可能过度联网；token 涨幅未实测。建议处置：接受继续，观察后可在工具描述进一步收紧触发条件。
3. **skill 绝对路径（含 home 用户名）进 LLM 上下文 + trace**：trace 原始报文会带 `/Users/<user>/.agents/skills/...`。建议处置：接受继续；介意可改返回相对 workspace 的路径 + 约定 `run_command` 以 skill 目录为 cwd。
4. **`_WORKSPACE` 定位未标【推理生成】**：`fs.py` 的 `_WORKSPACE = Path(__file__).resolve().parents[3]` 属「相对文件位置推导」，`shell.py` 同款 `_CWD` 已标【推理生成】、此处未标，轻微合规不一致。建议处置：补注释标注。

## ⑥ 未自动验证项（需人带 ApiKey 手工验）

- 真实对话「生成今日 AI 日报」端到端：`read_skill("ai-daily-report")` → `browser_search` 检索五维度 → `write_file` 写 `content.json` → `run_command("node scripts/render.mjs ...")` 渲染 → 交付 JPG（feature 已实测渲染脚本出图，检索与写文件需真实模型 + 网络）；
- 闲聊轮 web 检索是否误触发、token 涨幅是否可接受。

---

## ⑦ 修复记录（2026-09-22，实现方对黄灯 #1/#4 的修复 + 复验）

### 修复内容（`backend/agent/tools/fs.py`）

1. **黄灯 #1（安全）**：把「读写根」拆成两套——`_READ_ROOTS = (workspace, SKILLS_DIR)`（读/列可访问 skill 的
   `scripts/`/`references/`）、`_WRITE_ROOTS = (workspace,)`（**写仅 workspace**）。`write_file` 现在无法覆写
   `~/.agents/skills/*/SKILL.md`，`SKILLS_DIR` 降为只读，跨会话持久化注入面被消除。
2. **黄灯 #4（合规）**：`_WORKSPACE` 定位补【推理生成】标注（与 `shell.py` 的 `_CWD` 一致）。

### 新增/调整测试（`test/fs/test_fs.py`，7 → 8 条）

- 新增 `test_write_rejects_skills_dir_but_read_allows`：写 fake-skills 目录被拒、读允许；
- 原 3 条直接调 `_resolve` 的用例随签名改为 `_resolve(path, roots)`。

### 复验结果（机器可查，全绿）

```
pytest test/fs/ -q   ->  8 passed
pytest test/ -q      ->  53 passed, 1 warning（pydantic 存量告警）
功能复测：write_file 写 ~/.agents/skills/.../SKILL.md -> 「路径越界被拒绝（仅允许写入 workspace）」
          write_file 写 workspace 内文件 -> 「已写入」
```

### 复验后结论

- 黄灯 #1、#4 已修复并复验，不再成立；偏差 2 的措辞已同步到 proposal/feature（「写 workspace、读 workspace + SKILLS_DIR」）。
- 残留黄级（常驻 web 检索 token/误联网、skill 绝对路径进 trace）不阻塞，由人裁定接受或后续硬化。

---

## ⑧ 人工反馈的后续微调（验证后，未重跑独立验证）

1. **web 工具改标准名**：`browser_search` → `web_search`、`browser_fetch` → `web_fetch`（对齐 Claude/Codex 生态名，任意 skill 按此名调用）。纯命名，无逻辑改动。
2. **shell 工具改标准名**：`run_command` → `bash`（对齐 Claude Code 的 Bash 工具名；此前模型读 skill 后想调 `bash` 找不到、误报「没有 shell 执行权限」）。纯命名，闸门/风险分级逻辑不变。
3. **时间上下文**：`prompts.py` 新增 `TIME_SECTION`，`_get_system_prompt` 注入当前时间，修「今日 AI 日报」日期对不上。
4. **定位重述**：本轮目标 = 补齐「web + 文件 + shell + 时间」通用能力底座、服务**任意本地 skill**，日报只是第一个用例。

复验：`pytest test/ -q` 仍 **53 passed**；功能自检 system prompt 含「当前时间」、`web_search`/`web_fetch`/`bash` 常驻且无 `browser_*`/`run_command` 残留；`bash` 直跑 `node render.mjs` 实测出图。
