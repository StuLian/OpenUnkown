import { useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";

type AuthMode = "login" | "register";

export default function AuthOverlay() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const name = username.trim();
    if (!name || !password) {
      setError("请填写用户名和密码");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (mode === "login") {
        await login(name, password);
      } else {
        await register(name, password);
      }
      setPassword("");
    } catch (err) {
      setError("请求失败：" + (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-overlay">
      <div className="auth-card">
        <div className="auth-logo">O</div>
        <h2>OpenUnknown</h2>
        <div className="auth-sub">登录后配置模型 ApiKey，即刻开始对话</div>

        <div className="auth-tabs">
          <button
            className={"auth-tab" + (mode === "login" ? " active" : "")}
            onClick={() => setMode("login")}
          >
            登录
          </button>
          <button
            className={"auth-tab" + (mode === "register" ? " active" : "")}
            onClick={() => setMode("register")}
          >
            注册
          </button>
        </div>

        <form id="authForm" onSubmit={onSubmit}>
          <div className="form-row">
            <label>用户名</label>
            <input
              type="text"
              autoComplete="username"
              placeholder="3-32 个字符"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="form-row">
            <label>密码</label>
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="至少 6 位"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? (
            <div className="auth-error" style={{ display: "block" }}>
              {error}
            </div>
          ) : null}
          <button
            type="submit"
            className="btn btn-primary auth-submit"
            disabled={busy}
          >
            {mode === "login" ? "登录" : "注册"}
          </button>
        </form>

        <div className="auth-note">
          ApiKey 将加密存储于本地数据库，仅用于调用模型服务。
        </div>
      </div>
    </div>
  );
}
