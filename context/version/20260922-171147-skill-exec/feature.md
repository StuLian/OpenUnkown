# feature · 20260922-171147-skill-exec（补齐 skill 执行闭环）

> 状态：已提交
> 提交 hash：7d2341d
> 关联 proposal：本目录 `proposal.md`

## 一、新增文件系统工具 `backend/agent/tools/fs.py`（约 90 行）

- `read_file(path)` / `write_file(path, content)` / `list_files(path=".")`（均 sync @tool）。
- 路径安全：`_resolve()` 把相对路径相对项目根解析，`resolve()` 后做包含性校验，`../`/绝对越界/符号链接逃逸全拒。
- **读写根分离**：读/列根 = workspace + `SKILLS_DIR`（skill 的 `scripts/`/`references/` 需被读）；**写根 = 仅 workspace**
  （`write_file` 不能覆写 `~/.agents/skills/*/SKILL.md`，`SKILLS_DIR` 只读）。`write_file` 覆盖写入、父目录自动创建、落盘不弹确认。

## 二、通用能力底座（对齐 Claude/Codex，服务任意本地 skill）

> 定位：本轮不是「服务日报」，而是补齐「web + 文件 + shell + 时间」四件**通用能力底座**，
> 使**任意未知本地 skill**（只要依赖这四类能力）都能端到端跑通，`ai-daily-report` 只是第一个验证用例。

- **web 工具改标准名**：`browser_search` → `web_search`、`browser_fetch` → `web_fetch`（对齐 Claude/Codex 生态标准名，
  本地 skill 说明书按此名调用，模型无需再「翻译」）。文件仍为 `tools/browser_use.py`。
- **时间上下文**：`prompts.py` 新增 `TIME_SECTION`，`graph._get_system_prompt` 注入当前时间
  （`当前时间：YYYY-MM-DD HH:MM:SS 星期X`），解决「今日/本周」类 skill 不知道日期而臆造的问题。
- `_select_tools`：`web_search` / `web_fetch` / `read_file` / `write_file` / `list_files`
  与 `bash` / `read_skill` 一并**常驻绑定**，不再依赖 browse 意图。
- `router.py`：删除 `_BROWSE_KWS` / `_KEYWORD_MAP["browse"]` / `_ANCHORS["browse"]`（web 常驻后失去唯一消费方，与 feishu 同理清理）。

## 三、skill 路径暴露（skills/loader.py）

- `load_skill_doc` 返回正文前附一行 `skill 目录: <绝对路径>`，模型据此用绝对路径定位
  `scripts/`、写 `content.json`、跑 `node scripts/render.mjs`。

## 四、测试

- 新增 `test/fs/test_fs.py`（8 条）：`_resolve` 的 `../`/绝对越界/符号链接逃逸拒绝、写读回环、list_files、越界写拒绝、
  写 skills 目录拒绝但读允许（读写根分离）、读不存在文件。
- 全量 `pytest test/`：**53 passed**（skills 11 + shell 11 + fs 8 + 存量 23）。

## 五、验证（机器可查，全绿）

```
.venv/bin/python -c "import backend.main / backend.agent.graph"  ->  OK
.venv/bin/python -m pytest test/ -q                              ->  53 passed, 1 warning（pydantic 存量告警）
.venv/bin/python -m backend.eval.prompt_eval                     ->  全部通过
功能自检：read_skill 带 skill 目录路径；system prompt 含「当前时间」；「生成今日 AI 日报」轮绑定
          web_search/web_fetch/bash/read_skill/read_file/write_file/list_files 共 7 个通用工具；
          ai-daily-report 渲染脚本实测：node scripts/render.mjs → 20260918.jpg（1696×2528，sharp/librsvg）
```

## 六、未处理（已记 `context/backlog.md`）

- `write_file` 免确认但限定 workspace，恶意 skill 仍可写 workspace 内任意文件 → 后续可加「写关键路径才确认」；
- 常驻 web 检索 token 涨幅、闲聊误联网需观察；skill 相对路径渲染（bash cwd）仍靠绝对路径绕。

## commit

- hash：`7d2341ddf111fffc6f9beb72fee609e63ed6492f`（短 `7d2341d`）
