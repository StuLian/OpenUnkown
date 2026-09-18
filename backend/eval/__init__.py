"""离线评测包：RAG 检索质量与 prompt 行为的量化评测。

评测是开发/CI 工具，不走产品 HTTP 路径；通过 ``python -m backend.eval.rag_eval`` 等入口运行，
需要传入模型服务 ApiKey（评测脚本不从用户表读取，也不做任何兜底）。
"""
