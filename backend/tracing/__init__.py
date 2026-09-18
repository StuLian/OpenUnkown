"""trace 采集：一轮对话执行过程中收集完整原始报文，供落库与 Trace 轨迹复盘。"""
from backend.tracing.collector import TraceCollector, new_run_id

__all__ = ["TraceCollector", "new_run_id"]
