# 测试报告 · 20260918-trace-panel

## 一、结论
- 判灯：🟡（黄）

## 二、机器验证结果
| 检查 | 结果 |
|------|------|
| `import backend.main` | ✅ 通过 |
| `prompt_eval` | ✅ 全部通过（版本 1.0.0，四层结构） |
| `npm run typecheck` | ✅ 通过 |
| `npm run build` | ✅ 通过（3.5s，仅 chunk>500kB 警告，非错误） |
| eval 模块导入 | ✅ 通过 |
| TraceCollector 冒烟 | ✅ flag 判定 / 序列化正确 |
| 落库往返（临时库） | ✅ JSON 往返 / 筛选 / 越权隔离正确 |
| pytest | ❌ 未安装（且 `test/test_mcp_server.py` 是 mock 服务器，非测试） |

## 三、发现的问题
### 🟡 1. `record_llm_input` 覆盖而非追加（已修复，见修复记录第 1 轮）
多轮工具调用时 trace 只保留最后一轮 LLM 输入，与 docstring「完整原始报文」不符。已通过冒烟确认。
建议：改为按消息 id 去重后追加，否则轨迹复盘时中间轮次报文丢失。
> 修复时重新判定：覆盖式其实是对的（`_chat_node` 每次传入的都是「新建 system + 完整累计历史」，最后一次即完整报文）；真正的问题是落库丢失消息 `id` 与 docstring 不准确。

### 🟡 2. 新增核心逻辑零自动化测试
2123 行新逻辑（collector / store / 路由）无 pytest 覆盖。验证依赖一次性冒烟脚本，不沉淀为回归资产。
建议：把冒烟固化为 `test/test_trace_collector.py` + `test/test_runs_store.py`。

### 🟡 3. 存量文件逼近/超过 300 行阈值
`streaming.py` 431、`graph.py` 431、`db.py` 217，本次改动让前两者各 +73/+15。

## 四、修复记录
### 2026-09-18 · 第 1 轮（修复黄点 1）
- 重新判定：`record_llm_input` 的「覆盖式」实际正确——`_chat_node` 每次传入的都是「新建 system 消息 + 完整累计历史」，最后一次调用已包含整轮全部报文，不存在「中间轮次报文丢失」（原黄点源于错误的冒烟假设）。
- 真实修复（`backend/tracing/collector.py`）：
  1. `message_to_serializable` 增加消息 `id` 捕获（供轨迹面板关联消息）；
  2. docstring「完整原始报文」更正为「最后一次提交给模型的完整报文」（实际是压缩后的）；
  3. `record_llm_input` 增加按 id（tool 按 tool_call_id）去重，防御节点因 interrupt/重跑产生重复。
- 验证：模拟真实图流程（add_messages 累加）冒烟 —— 六条消息齐全、system 不重复、历史消息 id 已捕获、节点重跑不重复、序列化/flag 判定回归通过；`import backend.main` 通过。
