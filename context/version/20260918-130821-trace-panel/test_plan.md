# 测试计划 · 20260918-130821-trace-panel

## 一、机器可验（真实命令）
| 检查 | 命令 | 预期 |
|------|------|------|
| 后端 import | `.venv/bin/python -c "import backend.main"` | 无报错 |
| 单元测试 | `.venv/bin/python -m pytest test/ -q` | 全绿（注：项目未装 pytest，且 test/ 无真实用例，见报告） |
| 前端类型 | `npm run typecheck` | 无输出=通过 |
| 前端构建 | `npm run build` | 成功 |
| prompt 回归 | `.venv/bin/python -m backend.eval.prompt_eval` | 全部通过 |
| eval 导入 | import `backend.eval.metrics/rag_eval/report` | 无报错 |
| collector 冒烟 | 手写脚本 | flag 判定/序列化正确 |
| 落库往返 | 临时库往返脚本 | JSON 往返/筛选/越权正确 |

## 二、人工判断
- [ ] 多轮工具调用时 trace 是否应保留全部 LLM 输入（而非仅最后一轮）
- [ ] `final_answer` 是否允许混入工具调用前的中间文本
