import { useCallback, useEffect, useState } from "react";
import {
  deleteSessionRequest,
  fetchMcpServers,
  fetchModels,
  fetchModes,
  fetchSessions,
  fetchSettings,
} from "./api/endpoints";
import {
  LS_MODEL,
  LS_MODE,
  LS_SESSION,
  newSessionId,
} from "./lib/storage";
import type {
  McpServer,
  ModelOption,
  ModeOption,
  Session,
  SettingsInfo,
} from "./types";
import { AuthProvider, useAuth } from "./context/AuthContext";
import AuthOverlay from "./components/AuthOverlay";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import McpModal from "./components/McpModal";
import SettingsModal from "./components/SettingsModal";

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}

function AppShell() {
  const { user, ready, logout } = useAuth();

  const [models, setModels] = useState<ModelOption[]>([]);
  const [modes, setModes] = useState<ModeOption[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [settings, setSettings] = useState<SettingsInfo | null>(null);

  const [currentSessionId, setCurrentSessionId] = useState<string>(
    () => localStorage.getItem(LS_SESSION) ?? newSessionId()
  );
  const [currentModel, setCurrentModel] = useState<string>(
    () => localStorage.getItem(LS_MODEL) ?? ""
  );
  const [currentMode, setCurrentMode] = useState<string>(
    () => localStorage.getItem(LS_MODE) ?? ""
  );

  const [mcpOpen, setMcpOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // 登录后一次性加载模型/模式/会话/MCP/设置。
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const [modelsRes, modesRes, sessionsRes, mcpRes, settingsRes] =
          await Promise.all([
            fetchModels(),
            fetchModes(),
            fetchSessions(),
            fetchMcpServers(),
            fetchSettings(),
          ]);
        if (cancelled) return;

        setModels(modelsRes.models);
        setModes(modesRes.modes);
        setSessions(sessionsRes.sessions);
        setMcpServers(mcpRes.servers);
        setSettings(settingsRes);

        setCurrentModel((prev) => {
          const valid = modelsRes.models.some((m) => m.id === prev);
          const next = valid
            ? prev
            : modelsRes.default || modelsRes.models[0]?.id || "";
          localStorage.setItem(LS_MODEL, next);
          return next;
        });
        setCurrentMode((prev) => {
          const valid = modesRes.modes.some((m) => m.id === prev);
          const next = valid
            ? prev
            : modesRes.default || modesRes.modes[0]?.id || "";
          localStorage.setItem(LS_MODE, next);
          return next;
        });
      } catch (e) {
        console.error("加载应用数据失败", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const refreshSessions = useCallback(async () => {
    try {
      const d = await fetchSessions();
      setSessions(d.sessions);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshMcp = useCallback(async () => {
    try {
      const d = await fetchMcpServers();
      setMcpServers(d.servers);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    try {
      setSettings(await fetchSettings());
    } catch {
      /* ignore */
    }
  }, []);

  function selectSession(id: string) {
    setCurrentSessionId(id);
    localStorage.setItem(LS_SESSION, id);
  }

  function newSession() {
    const id = newSessionId();
    setCurrentSessionId(id);
    localStorage.setItem(LS_SESSION, id);
  }

  async function deleteSession(id: string) {
    if (!confirm("确定删除这个对话吗？")) return;
    try {
      await deleteSessionRequest(id);
      if (id === currentSessionId) {
        newSession();
      }
      await refreshSessions();
    } catch (e) {
      console.error("删除会话失败", e);
    }
  }

  function handleLogout() {
    logout();
    // 退出后重置本地会话 id，避免不同用户复用同一会话。
    const id = newSessionId();
    setCurrentSessionId(id);
    localStorage.setItem(LS_SESSION, id);
  }

  if (!ready) {
    return <div className="app-loading">加载中…</div>;
  }

  if (!user) {
    return <AuthOverlay />;
  }

  const hasApiKey = settings ? settings.current.has_key : user.has_api_key;
  const mcpEnabledCount = mcpServers.filter((s) => s.enabled).length;

  return (
    <div className="app">
      <Sidebar
        user={user}
        sessions={sessions}
        currentSessionId={currentSessionId}
        hasApiKey={hasApiKey}
        mcpEnabledCount={mcpEnabledCount}
        mcpTotalCount={mcpServers.length}
        onSelectSession={selectSession}
        onNewSession={newSession}
        onDeleteSession={(id) => void deleteSession(id)}
        onLogout={handleLogout}
        onOpenMcp={() => setMcpOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main>
        <header>
          <div>
            <h1>OpenUnknown</h1>
            <div className="sub">基于 LangGraph · 支持 MCP 扩展</div>
          </div>
          <div className="mode-picker">
            <label htmlFor="modeSelect">模式</label>
            <select
              id="modeSelect"
              value={currentMode}
              onChange={(e) => {
                setCurrentMode(e.target.value);
                localStorage.setItem(LS_MODE, e.target.value);
              }}
            >
              {modes.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
          <div className="model-picker">
            <label htmlFor="modelSelect">模型</label>
            <select
              id="modelSelect"
              value={currentModel}
              onChange={(e) => {
                setCurrentModel(e.target.value);
                localStorage.setItem(LS_MODEL, e.target.value);
              }}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        </header>

        <ChatView
          sessionId={currentSessionId}
          model={currentModel}
          mode={currentMode}
          modes={modes}
          hasApiKey={hasApiKey}
          onOpenSettings={() => setSettingsOpen(true)}
          onSettled={() => void refreshSessions()}
        />
      </main>

      <McpModal
        open={mcpOpen}
        onClose={() => setMcpOpen(false)}
        servers={mcpServers}
        onChanged={() => void refreshMcp()}
      />
      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
        onChanged={() => void refreshSettings()}
      />
    </div>
  );
}
