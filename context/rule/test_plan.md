# 测试计划模板

> 写代码 agent 在实现完成后填写。强制区分「机器可验」与「只能人看」。

# 测试计划 · <变更 ID>

## 一、机器可验（真实命令，写退出码/断言结果）
| 检查 | 命令 | 预期 |
|------|------|------|
| 后端 import | `.venv/bin/python -c "import backend.main"` | 无报错 |
| 单元测试 | `.venv/bin/python -m pytest test/ -q` | 全绿 |
| 前端类型 | `npm run typecheck` | 无输出=通过 |
| 前端构建 | `npm run build` | 成功 |
| prompt 回归 | `.venv/bin/python -m backend.eval.prompt_eval` | 全部通过 |

## 二、人工判断（机器查不了，需人看）
- [ ] ...
