import { useEffect, useState } from "react";
import {
  clearMemoriesRequest,
  deleteMemoryRequest,
  fetchMemories,
} from "../api/endpoints";
import type { MemoryFact } from "../types";
import Modal from "./Modal";

/**
 * 「我的记忆」独立弹窗：列出系统自动记住的长期事实，支持单条删除与一键清空。
 *
 * 入口在左侧栏底部（与「Trace 轨迹」「模型设置」平级）。此前挂在设置弹窗最底部，
 * 可发现性差，故独立成弹窗（见 context/version/20260920-193807-memory-entry）。
 * 记忆为空时给出明确空态；加载失败给出显式错误，避免用户误以为「系统没记我的事」。
 */
export default function MemoryModal({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged?: (count: number) => void;
}) {
  const [memories, setMemories] = useState<MemoryFact[]>([]);
  const [failed, setFailed] = useState(false);

  // 弹窗打开时拉取一次；失败显式提示（不静默空态）。
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setFailed(false);
    void fetchMemories()
      .then((d) => {
        if (!cancelled) {
          setMemories(d.facts);
          onChanged?.(d.total);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMemories([]);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function handleDelete(id: string) {
    try {
      await deleteMemoryRequest(id);
      const next = memories.filter((m) => m.id !== id);
      setMemories(next);
      onChanged?.(next.length);
    } catch {
      /* 删除失败保持原状，用户可重试 */
    }
  }

  async function handleClear() {
    if (!confirm("确定清空全部长期记忆吗？清空后系统将不再记得你的偏好与长期事实。")) {
      return;
    }
    try {
      await clearMemoriesRequest();
      setMemories([]);
      onChanged?.(0);
    } catch {
      /* ignore */
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      small
      title="我的记忆"
      subtitle="系统在对话中自动记住的、关于你的长期事实"
    >
      <div className="memory-box">
        <div className="memory-head">
          <span className="memory-title">共 {memories.length} 条</span>
          {memories.length > 0 ? (
            <button
              type="button"
              className="btn-icon del"
              onClick={() => void handleClear()}
            >
              清空全部
            </button>
          ) : null}
        </div>

        {failed ? (
          <div className="memory-error">记忆加载失败，请关闭后重试</div>
        ) : memories.length === 0 ? (
          <div className="memory-empty">系统还没有为你保存任何长期记忆</div>
        ) : (
          <div className="memory-list">
            {memories.map((m) => (
              <div className="memory-item" key={m.id}>
                <span className="memory-text">{m.content}</span>
                <span className="memory-time">
                  {new Date(m.created_at * 1000).toLocaleDateString()}
                </span>
                <button
                  type="button"
                  className="btn-icon del"
                  title="删除这条记忆"
                  onClick={() => void handleDelete(m.id)}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="settings-note">
          这些是系统在对话中自动记住的、关于你的长期事实，后续对话会作为背景注入。
          记错或不想保留的，可随时删除。
          <br />
          说明：这里只包含「长期事实」；各会话的对话摘要随该会话一起删除（在左侧会话列表删除即可）。
        </div>
      </div>
    </Modal>
  );
}
