import { useEffect, useState, type ReactNode } from "react";
import { fetchUsage } from "../api/endpoints";
import type { UsageStats } from "../types";
import Modal from "./Modal";

/**
 * 「用量统计」独立弹窗：展示 token 消耗的总计、按模型、按日期。
 *
 * 入口在左侧栏底部（与「我的记忆」「Trace 轨迹」平级）。此前嵌在设置弹窗里，
 * 与「配置 ApiKey」这类操作混在一起，故独立成弹窗。
 */
export default function UsageModal({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged?: (count: number) => void;
}) {
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setFailed(false);
    void fetchUsage()
      .then((u) => {
        if (!cancelled) {
          setUsage(u);
          onChanged?.(u.totals.requests);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUsage(null);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  let body: ReactNode;
  if (failed) {
    body = <div className="memory-error">用量加载失败，请关闭后重试</div>;
  } else if (!usage || usage.totals.requests === 0) {
    body = <div className="memory-empty">还没有产生任何调用记录</div>;
  } else {
    body = (
      <>
        <div className="usage-summary">
          共 {usage.totals.requests} 次请求 · 输入 {usage.totals.input_tokens} · 输出{" "}
          {usage.totals.output_tokens} · 合计 {usage.totals.total_tokens} tokens
        </div>

        {usage.by_model.length > 0 ? (
          <>
            <div className="usage-title">按模型</div>
            <table className="usage-table">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>次数</th>
                  <th>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_model.map((m) => (
                  <tr key={m.model}>
                    <td>{m.model}</td>
                    <td>{m.requests}</td>
                    <td>{m.total_tokens}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}

        {usage.by_day.length > 0 ? (
          <>
            <div className="usage-title">按日期</div>
            <table className="usage-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>次数</th>
                  <th>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_day.map((d) => (
                  <tr key={d.date}>
                    <td>{d.date}</td>
                    <td>{d.requests}</td>
                    <td>{d.total_tokens}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </>
    );
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      small
      title="用量统计"
      subtitle="本账号的模型调用次数与 token 消耗"
    >
      <div className="usage-modal">{body}</div>
    </Modal>
  );
}
