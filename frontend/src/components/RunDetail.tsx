import type { ReactNode } from "react";
import type { RetrievedDoc, RunDetail as RunDetailData } from "../types";

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

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function FlagBadge({ flag }: { flag: string }) {
  return <span className="flag-badge">{FLAG_LABELS[flag] ?? flag}</span>;
}

/** 把任意内容格式化为可读文本（对象则 JSON 美化）。 */
function asText(value: unknown): string {
  return typeof value === "string"
    ? value
    : JSON.stringify(value, null, 2);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="run-section">
      <h4 className="run-section-title">{title}</h4>
      {children}
    </section>
  );
}

function MessageCard({ msg, index }: { msg: RunDetailData["messages"][number]; index: number }) {
  const contentText = asText(msg.content);
  return (
    <details className="trace-msg" open={index === 0}>
      <summary>
        <span className={"trace-msg-type" + (msg.kind ? ` ${msg.kind}` : "")}>
          {msg.kind ?? msg.type}
        </span>
        {msg.name ? <span className="trace-msg-name">{msg.name}</span> : null}
        <span className="trace-msg-len">{contentText.length} 字</span>
      </summary>
      <pre className="trace-pre">{contentText}</pre>
      {msg.tool_calls && msg.tool_calls.length > 0 ? (
        <pre className="trace-pre">{JSON.stringify(msg.tool_calls, null, 2)}</pre>
      ) : null}
    </details>
  );
}

/** RAG 检索结果可视化：每家酒店一个相关度分数条，top1 高亮。 */
function RetrievedDocsView({ docs }: { docs: RetrievedDoc[] }) {
  const scores = docs.map((d) => (typeof d.score === "number" ? d.score : 0));
  const maxScore = Math.max(...scores, 0.0001);
  return (
    <div className="retrieved-list">
      {docs.map((d, i) => {
        const score = typeof d.score === "number" ? d.score : 0;
        const pct = Math.max(0, Math.min(100, (score / maxScore) * 100));
        return (
          <div className={"retrieved-item" + (i === 0 ? " top" : "")} key={i}>
            <div className="retrieved-head">
              <span className="retrieved-rank">#{i + 1}</span>
              <span className="retrieved-name">{d.name}</span>
              {i === 0 ? <span className="retrieved-top-badge">top1</span> : null}
              <span className="retrieved-score">{score.toFixed(3)}</span>
            </div>
            <div className="retrieved-bar">
              <div className="retrieved-bar-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface RunDetailProps {
  run: RunDetailData | null;
  onClose: () => void;
}

export default function RunDetail({ run, onClose }: RunDetailProps) {
  if (!run) return null;

  const usage = run.usage || { input_tokens: 0, output_tokens: 0, total_tokens: 0 };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-dialog modal-dialog-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title">
            <h3>Trace 详情</h3>
            <div className="modal-subtitle">{run.id}</div>
          </div>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body run-detail">
          <Section title="基本信息">
            <div className="run-kv">
              <span>模型：{run.model}</span>
              <span>模式：{run.mode}</span>
              <span>prompt：{run.prompt_version || "未知"}</span>
              <span>耗时：{run.latency_ms} ms</span>
              <span>时间：{fmtTime(run.created_at)}</span>
              <span>
                Tokens：输入 {usage.input_tokens} · 输出 {usage.output_tokens} · 合计{" "}
                {usage.total_tokens}
              </span>
            </div>
            {run.flags.length > 0 ? (
              <div className="run-flags">
                {run.flags.map((f) => (
                  <FlagBadge key={f} flag={f} />
                ))}
              </div>
            ) : null}
            {run.error ? <pre className="trace-pre error">{run.error}</pre> : null}
          </Section>

          <Section title="用户输入">
            <pre className="trace-pre">{run.input_text}</pre>
          </Section>

          <Section title={`原始报文（${run.messages.length} 条）`}>
            {run.messages.map((m, i) => (
              <MessageCard key={i} msg={m} index={i} />
            ))}
          </Section>

          {run.tool_calls.length > 0 ? (
            <Section title={`工具调用（${run.tool_calls.length}）`}>
              <pre className="trace-pre">{JSON.stringify(run.tool_calls, null, 2)}</pre>
            </Section>
          ) : null}

          {run.tool_outputs.length > 0 ? (
            <Section title="工具返回">
              {run.tool_outputs.map((o) => (
                <details className="trace-msg" key={o.id}>
                  <summary>
                    <span className="trace-msg-type">tool</span>
                    <span className="trace-msg-name">{o.name}</span>
                    <span className="trace-msg-len">{o.output.length} 字</span>
                  </summary>
                  <pre className="trace-pre">{o.output}</pre>
                </details>
              ))}
            </Section>
          ) : null}

          {run.retrieved_docs.length > 0 ? (
            <Section title={`RAG 检索结果（${run.retrieved_docs.length}）`}>
              <RetrievedDocsView docs={run.retrieved_docs} />
            </Section>
          ) : null}

          <Section title="最终回答">
            <pre className="trace-pre answer">{run.final_answer || "(空)"}</pre>
          </Section>

          {run.grounding ? (
            <Section title="幻觉闸门判定">
              <div className="run-kv">
                <span>
                  判定：
                  {run.grounding.grounded ? "有据（grounded）" : "无据（ungrounded）"}
                </span>
                <span>
                  置信度：
                  {typeof run.grounding.confidence === "number"
                    ? run.grounding.confidence.toFixed(2)
                    : "—"}
                </span>
              </div>
              {run.grounding.ungrounded_spans?.length ? (
                <div className="run-flags">
                  {run.grounding.ungrounded_spans.map((s, i) => (
                    <span key={i} className="flag-badge">
                      无据片段：{s}
                    </span>
                  ))}
                </div>
              ) : null}
              {run.grounding.reason ? (
                <pre className="trace-pre">{run.grounding.reason}</pre>
              ) : null}
            </Section>
          ) : null}

          {run.feedback.length > 0 ? (
            <Section title={`反馈（${run.feedback.length}）`}>
              {run.feedback.map((f) => (
                <div className="feedback-item" key={f.id}>
                  <span className="feedback-rating">{f.rating > 0 ? "👍" : f.rating < 0 ? "👎" : "·"}</span>
                  {f.tags.map((t) => (
                    <FlagBadge key={t} flag={t} />
                  ))}
                  {f.comment ? <span className="feedback-comment-text">{f.comment}</span> : null}
                  <span className="feedback-time">{fmtTime(f.created_at)}</span>
                </div>
              ))}
            </Section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
