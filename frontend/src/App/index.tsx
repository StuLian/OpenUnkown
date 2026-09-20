import { useCallback, useEffect, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  deleteSessionRequest,
  fetchMcpServers,
  fetchMemories,
  fetchModels,
  fetchModes,
  fetchSessions,
  fetchSettings,
  fetchUsage,
} from "../api/endpoints";
import {
  LS_MODEL,
  LS_MODE,
  LS_SESSION,
  newSessionId,
} from "../lib/storage";
import type {
  McpServer,
  ModelOption,
  ModeOption,
  Session,
  SettingsInfo,
} from "../types";
import { AuthProvider, useAuth } from "../context/AuthContext";
import AppHeader from "./AppHeader";
import AuthOverlay from "../components/AuthOverlay";
import Sidebar from "../components/Sidebar";
import ChatView from "../components/ChatView";
import TracesPanel from "../components/TracesPanel";
import Modals from "./Modals";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </AuthProvider>
  );
}

function AppShell() {
  const { user, ready, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isTraces = location.pathname === "/traces";

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
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [memoryCount, setMemoryCount] = useState(0);
  const [usageCount, setUsageCount] = useState(0);

  // 记忆条数 / 用量总数：供左下角状态灯用，失败静默（不影响核心功能）。
  const refreshCounts = useCallback(async () => {
    try {
      const mem = await fetchMemories();
      setMemoryCount(mem.total);
    } catch {
      /* ignore */
    }
    try {
      const u = await fetchUsage();
      setUsageCount(u.totals.requests);
    } catch {
      /* ignore */
    }
  }, []);

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
        void refreshCounts();

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
    navigate("/");
  }

  function newSession() {
    const id = newSessionId();
    setCurrentSessionId(id);
    localStorage.setItem(LS_SESSION, id);
    navigate("/");
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
        view={isTraces ? "traces" : "chat"}
        onSelectSession={selectSession}
        onNewSession={newSession}
        onDeleteSession={(id) => void deleteSession(id)}
        onLogout={handleLogout}
        onOpenMcp={() => setMcpOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenTraces={() => navigate("/traces")}
        onOpenMemory={() => setMemoryOpen(true)}
        onOpenUsage={() => setUsageOpen(true)}
        memoryCount={memoryCount}
        usageCount={usageCount}
      />

      <main>
        <AppHeader
          isTraces={isTraces}
          modes={modes}
          models={models}
          currentMode={currentMode}
          currentModel={currentModel}
          onChangeMode={(id) => {
            setCurrentMode(id);
            localStorage.setItem(LS_MODE, id);
          }}
          onChangeModel={(id) => {
            setCurrentModel(id);
            localStorage.setItem(LS_MODEL, id);
          }}
          onBack={() => navigate("/")}
        />

        <Routes>
          <Route
            path="/"
            element={
              <ChatView
                sessionId={currentSessionId}
                model={currentModel}
                mode={currentMode}
                modes={modes}
                hasApiKey={hasApiKey}
                onOpenSettings={() => setSettingsOpen(true)}
                onSettled={() => {
                  void refreshSessions();
                  void refreshCounts();
                }}
              />
            }
          />
          <Route path="/traces" element={<TracesPanel />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <Modals
        mcpOpen={mcpOpen}
        settingsOpen={settingsOpen}
        memoryOpen={memoryOpen}
        usageOpen={usageOpen}
        mcpServers={mcpServers}
        settings={settings}
        onCloseMcp={() => setMcpOpen(false)}
        onCloseSettings={() => setSettingsOpen(false)}
        onCloseMemory={() => setMemoryOpen(false)}
        onCloseUsage={() => setUsageOpen(false)}
        onMcpChanged={() => void refreshMcp()}
        onSettingsChanged={() => void refreshSettings()}
        onMemoryChanged={(n) => setMemoryCount(n)}
        onUsageChanged={(n) => setUsageCount(n)}
      />
    </div>
  );
}
