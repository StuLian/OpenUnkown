import type { Session } from "../types";

interface SidebarProps {
  user: { username: string } | null;
  sessions: Session[];
  currentSessionId: string;
  hasApiKey: boolean;
  mcpEnabledCount: number;
  mcpTotalCount: number;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  onLogout: () => void;
  onOpenMcp: () => void;
  onOpenSettings: () => void;
}

export default function Sidebar({
  user,
  sessions,
  currentSessionId,
  hasApiKey,
  mcpEnabledCount,
  mcpTotalCount,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onLogout,
  onOpenMcp,
  onOpenSettings,
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
      </div>
    </aside>
  );
}
