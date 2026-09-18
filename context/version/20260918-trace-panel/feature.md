# feature · 20260918-trace-panel

> 状态：已提交
> 关联 proposal：无（本变更早于 context 体系建立，属历史变更，见 test_report 黄点）

## 实际改动
- 新增 `TraceCollector` 采集每轮对话原始报文/工具调用/召回，落 `runs` 表并自动打 flag（`tool_error`/`no_answer`/`error`/`pending_confirm`）
- 新增 `feedback` 表 + `/api/runs` 三接口（列表/详情/反馈，均做 user_id 越权隔离）
- 前端新增 Trace 轨迹面板 + 消息反馈栏，引入 `react-router-dom`
- 新增 `eval/` 离线评测（recall@k/MRR/nDCG + prompt 结构回归）
- `prompts.py` 分层重构 + `PROMPT_VERSION` 语义版本

## diff 摘要（基于 git diff 真实输出）
- 33 files changed, +2123 / -80
- 新文件：`backend/tracing/`、`backend/eval/`、`store/{runs,feedback}.py`、`api/routers/runs.py`、`frontend/components/{TracesPanel,RunDetail}.tsx`

## 与 proposal 的偏差
- 无 proposal（历史变更）

## commit
- hash：`535fd3ae5b84c499550fb25d5a01f5198934b113`
