"""trace 与用户反馈接口（Trace 轨迹面板后端）。

列表只返回摘要（不含体积大的原始报文），详情按 run_id 单独取全文；
反馈提交后即进入 feedback 表，并能在列表里按标签筛选。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend import store
from backend.api.schemas import FeedbackRequest
from backend.auth.deps import get_current_user_id

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(
    flag: str | None = Query(None, description="按自动/用户标记筛选，如 tool_error / hallucination"),
    model: str | None = Query(None),
    mode: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """分页列出当前用户的 run trace，可按 flag/model/mode 筛选。"""
    return {
        "runs": store.list_runs(
            user_id, flag=flag, model=model, mode=mode, limit=limit, offset=offset
        ),
        "total": store.count_runs(user_id, flag=flag, model=model, mode=mode),
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
def get_stats(user_id: str = Depends(get_current_user_id)) -> dict:
    """幻觉闸门相关统计（判定次数 / 无据次数 / 幻觉风险标记数 / 总轮数）。"""
    return store.run_stats(user_id)


@router.get("/{run_id}")
def get_run(run_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    """返回某条 run 的完整 trace（原始报文、工具调用、召回、用量、反馈）。"""
    run = store.get_run(user_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="trace 不存在或无权访问")
    return run


@router.post("/{run_id}/feedback")
def submit_feedback(
    run_id: str,
    req: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """提交对某轮回答的反馈（run_id 从路径取）。"""
    run = store.get_run(user_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="trace 不存在或无权访问")
    return store.insert_feedback(
        user_id, run_id, run["session_id"], req.rating, req.tags, req.comment
    )
