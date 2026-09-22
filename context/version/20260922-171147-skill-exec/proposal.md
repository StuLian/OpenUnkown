# 变更提案 · 补齐 skill 执行闭环（文件工具 + 通用能力常驻 + skill 路径暴露）

> 状态：已确认（人工批准「开始实现」）
> 变更 ID：20260922-171147-skill-exec
> 变更类型：新功能
> 分级：高风险（新增文件读写面 + 常驻绑定 web 检索）

## 0. 历史回溯（仅 bug 修复填写）
- 不适用（新功能，非 bug）。

## 1. 目标（一句话）
让「需要联网检索 + 读写文件 + 跑脚本」的本地 skill（如 `ai-daily-report`）能端到端执行：新增文件系统
工具、把 web 检索纳入常驻通用能力、并让模型能拿到 skill 的绝对路径去跑渲染脚本。

## 2. 验收标准（怎么算「对」）
- [ ] `ai-daily-report` 端到端跑通：检索 5 维度 → 写 `content.json` → `node scripts/render.mjs` 渲染 → 产出 JPG；
- [ ] `read_file` / `write_file` / `list_files` 路径安全：`../`、绝对路径越界、符号链接逃逸被拒；读可访问 workspace + `SKILLS_DIR`、**写仅 workspace**；
- [ ] `write_file` 落盘不弹确认（对齐 Claude Code），但**仅 workspace**（不能覆写 `SKILLS_DIR` 内 skill 说明书）；`run_command` 的写命令确认闸门不受影响；
- [ ] `browser_search` / `browser_fetch` + 文件三工具常驻绑定，闲聊 / 天气 / 酒店 / MCP 不回归；
- [ ] `read_skill` 返回带 skill 绝对目录路径，模型能用绝对路径运行 skill 内脚本；
- [ ] ≥1 条 pytest：文件路径安全 + 读写 + list_files。

## 3. 依据（需求依据 + 技术依据）
- **需求依据**：用户实测「生成今日 AI 日报」失败——agent 不具备 web 检索与 write_file 能力。
- **技术依据（已查证）**：
  - `ai-daily-report` SKILL.md 四步：① 检索五维度 ② 写 `content.json`（字段见 `references/content-schema.md`）
    ③ `node scripts/render.mjs --content content.json --out .` 渲染 ④ 交付 JPG；
  - 现状 `browser_search` / `browser_fetch` 存在，但「生成今日的 AI 日报」实测 `_hit` 各意图全 False → **本轮不绑定任何搜索工具**；
  - 无 `write_file` / `read_file` / `list_files`；`run_command` 固定 cwd=项目根、模型拿不到 skill 绝对路径 → 渲染脚本跑不起来；
  - 现有路径安全先例：`backend/agent/skills/loader.py` 的 `resolve_within`（`resolve()` 包含性校验）可复用。

## 4. 方案（怎么做 + 为什么选它）
一句话：新增 `tools/fs.py`（文件三工具 + workspace 路径安全）、把 web 检索与文件工具纳入「常驻通用能力」、
`read_skill` 附上 skill 绝对路径。**理由**：Claude/Codex 的「Bash + 文件系统 + web」三件套，本项目已补 Bash
（`run_command`），本轮补齐「文件系统」并让 web 常驻，skill 即闭环。**备选**：为每个 skill 的渲染单独做工具——不可行，skill 是动态的。

- **`tools/fs.py`（新）**：`read_file(path)` / `write_file(path, content)` / `list_files(path=".")`，
  自实现 `_resolve` 做 `resolve()` 包含性校验；读/列根 = workspace + `SKILLS_DIR`，**写根 = 仅 workspace**；
  `write_file` 落盘不弹确认但不能写 skill 说明书。
- **`graph._select_tools`**：`browser_search` / `browser_fetch` + 文件三工具加入「常驻通用能力」
  （与 `run_command` / `read_skill` 同级），不再依赖 browse 意图；weather/map/hotel/MCP 仍按意图绑定。
- **`skills/loader.load_skill_doc`**：返回正文前附一行 `skill 路径: <绝对目录>`，模型据此用绝对路径跑
  `node <skill>/scripts/render.mjs --content <skill>/content.json --out <skill>`。
- **工具改标准名（人工反馈微调）**：`browser_search` → `web_search`、`browser_fetch` → `web_fetch`，对齐 Claude/Codex 生态标准名，任意本地 skill 按此名调用。
- **时间上下文（人工反馈微调）**：`prompts.py` 新增 `TIME_SECTION`，`_get_system_prompt` 注入当前时间，解决「今日/本周」类 skill 臆造日期。

## 5. 影响面（改哪些 / 明确不碰哪些）
- **改**：新增 `tools/fs.py`；`tools/__init__.py`（挂文件三工具）；`graph.py`（`_select_tools` 常驻分支 + `_get_all_tools`）；
  `skills/loader.py`（`load_skill_doc` 附路径）；`test/fs/`；`AGENTS.md` §3/§6（模块职责 + 通用能力约定）。
- **明确不碰**：`run_command` 的写命令确认闸门、store/DB、api 路由、router 的 weather/map/hotel 意图、`shell.py`。

## 6. 风险与不确定点
1. **文件读写面（红）**：新增任意文件读写。缓解：严格复用 `resolve_within` 的 workspace 路径安全（`../`/绝对/符号链接逃逸全拒），收尾人工审查；
2. **常驻 web 检索（黄）**：闲聊轮也带 browser 工具，模型可能过度联网。缓解：工具描述强调「仅任务需要时使用」；token 涨幅收尾观察；
3. **write_file 免确认（黄）**：workspace 内写入放行，恶意 skill 可写任意 workspace 文件。缓解：限定 workspace；后续可加「写关键路径才确认」；
4. **渲染环境依赖（黄）**：`node scripts/render.mjs` 需本机 `node` + 光栅化器（sharp/rsvg-convert/sips/…），sips 为 macOS 自带兜底 → 收尾实测本机是否出图。

## 7. 验证计划（预览）
- 机器可查：`import` 通过、`pytest test/fs/`（路径安全/读写/list_files）、`prompt_eval`、前端 `typecheck`/`build`（若有前端改动）；
- 人工判断：真实「生成今日 AI 日报」端到端跑通、产出 JPG；闲聊轮 web 检索不误触发。
