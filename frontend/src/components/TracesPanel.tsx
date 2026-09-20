import { useEffect, useState } from "react";
import { fetchRunDetail, fetchRuns } from "../api/endpoints";
import type { RunDetail as RunDetailData, RunsPage } from "../types";
import RunDetail from "./RunDetail";

const FLAG_LABELS: Record<string, string> = {
  error: "错误",
  tool_error: "工具异常",
  no_answer: "无答案",
  pending_confirm: "待确认",
  memory_injected: "注入记忆",
  hallucination: "幻觉",
  irrelevant: "答非所问",
  bad: "差评",
};

const FLAG_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部" },
  { value: "memory_injected", label: "注入记忆" },
  { value: "tool_error", label: "工具异常" },
  { value: "no_answer", label: "无答案" },
  { value: "error", label: "错误" },
  { value: "pending_confirm", label: "待确认" },
  { value: "hallucination", label: "幻觉" },
  { value: "irrelevant", label: "答非所问" },
  { value: "bad", label: "差评" },
];

const PAGE_SIZE = 30;

export default function TracesPanel() {
  const [flag, setFlag] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<RunsPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetailData | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRuns({ flag: flag || undefined, limit: PAGE_SIZE, offset })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message || "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [flag, offset]);

  async function openDetail(id: string) {
    try {
      setDetail(await fetchRunDetail(id));
    } catch {
      setDetail(null);
    }
  }

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="trace-panel">
      <div className="trace-toolbar">
        <label htmlFor="traceFlag">筛选</label>
        <select
          id="traceFlag"
          value={flag}
          onChange={(e) => {
            setFlag(e.target.value);
            setOffset(0);
          }}
        >
          {FLAG_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="trace-total">共 {total} 条</span>
      </div>

      {error ? <div className="trace-empty">{error}</div> : null}
      {loading && !data ? <div className="trace-empty">加载中…</div> : null}
      {data && data.runs.length === 0 ? (
        <div className="trace-empty">暂无记录，先在对话里跑几轮再来复盘</div>
      ) : null}

      <div className="trace-list">
        {data?.runs.map((r) => (
          <div
            className="trace-item"
            key={r.id}
            onClick={() => void openDetail(r.id)}
          >
            <div className="trace-item-head">
              <span className="trace-input">{r.input_text || "(空输入)"}</span>
              <span className="trace-meta">
                {r.model} · {r.mode} · {r.latency_ms}ms
              </span>
            </div>
            {r.flags.length > 0 ? (
              <div className="trace-flags">
                {r.flags.map((f) => (
                  <span key={f} className="flag-badge">
                    {FLAG_LABELS[f] ?? f}
                  </span>
                ))}
              </div>
            ) : null}
            {r.final_answer_preview ? (
              <div className="trace-answer">{r.final_answer_preview}</div>
            ) : null}
            <div className="trace-item-foot">
              <span className="trace-time">
                {new Date(r.created_at * 1000).toLocaleString()}
              </span>
              {r.feedback_count > 0 ? (
                <span className="trace-feedback">反馈 {r.feedback_count}</span>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      {totalPages > 1 ? (
        <div className="trace-pager">
          <button
            className="btn btn-secondary"
            disabled={offset === 0}
            onClick={() => setOffset((p) => Math.max(0, p - PAGE_SIZE))}
          >
            上一页
          </button>
          <span className="trace-page">
            {page} / {totalPages}
          </span>
          <button
            className="btn btn-secondary"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((p) => p + PAGE_SIZE)}
          >
            下一页
          </button>
        </div>
      ) : null}

      <RunDetail run={detail} onClose={() => setDetail(null)} />
    </div>
  );
}
