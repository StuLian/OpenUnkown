import type { ReactNode } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  small?: boolean;
  title: string;
  subtitle?: string;
  children: ReactNode;
}

/** 通用弹窗：遮罩点击关闭、右上角关闭按钮、标题区。 */
export default function Modal({
  open,
  onClose,
  small = false,
  title,
  subtitle,
  children,
}: ModalProps) {
  if (!open) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={"modal-dialog" + (small ? " modal-dialog-sm" : "")}>
        <div className="modal-header">
          <div className="modal-title">
            <h3>{title}</h3>
            {subtitle ? <span className="modal-subtitle">{subtitle}</span> : null}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
