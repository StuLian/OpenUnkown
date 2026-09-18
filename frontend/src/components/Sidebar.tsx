import type { Session } from "../types";

interface SidebarProps {
  user: { username: string } | null;
  sessions: Session[];
  currentSessionId: string;
  hasApiKey: boolean;
  mcpEnabledCount: number;
  mcpTotalCount: number;
  view: "chat" | "traces";
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  onLogout: () => void;
  onOpenMcp: () => void;
  onOpenSettings: () => void;
  onOpenTraces: () => void;
}

export default function Sidebar({
  user,
  sessions,
  currentSessionId,
  hasApiKey,
  mcpEnabledCount,
  mcpTotalCount,
  view,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onLogout,
  onOpenMcp,
  onOpenSettings,
  onOpenTraces,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="logo">O</div>
        <div className="name">OpenUnknown</div>
      </div>

      <div className="new-btn" onClick={onNewSession}>
        + 新建对话
      </div>

      <div className="session-list">
        {sessions.length === 0 ? (
          <div
            style={{
              color: "var(--muted)",
              fontSize: 12,
              padding: "10px",
              textAlign: "center",
            }}
          >
            暂无历史对话
          </div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={"session-item" + (s.id === currentSessionId ? " active" : "")}
              onClick={() => onSelectSession(s.id)}
            >
              <div className="title">{s.title || "新对话"}</div>
              <button
                className="del"
                title="删除"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(s.id);
                }}
              >
                x
              </button>
            </div>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        <div className="user-row">
          <span className="user-name">{user?.username ?? "未登录"}</span>
          <button className="btn-icon" title="退出登录" onClick={onLogout}>
            退出
          </button>
        </div>
        <button className="mcp-entry-btn" onClick={onOpenMcp}>
          <span className="mcp-icon">⚙</span>
          <span>MCP 扩展管理</span>
          <span className="mcp-count-badge">
            {mcpEnabledCount}/{mcpTotalCount}
          </span>
        </button>
        <button className="mcp-entry-btn" onClick={onOpenSettings}>
          <span className="mcp-icon">⛭</span>
          <span>模型设置</span>
          <span
            className={"settings-status-dot" + (hasApiKey ? " on" : "")}
            title={hasApiKey ? "已配置 ApiKey" : "未配置 ApiKey"}
          />
        </button>
        <button
          className={"mcp-entry-btn" + (view === "traces" ? " active" : "")}
          onClick={onOpenTraces}
        >
          <span className="mcp-icon">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </span>
          <span>Trace 轨迹</span>
          <span className="mcp-count-badge trace-badge">复盘</span>
        </button>
      </div>
    </aside>
  );
}
