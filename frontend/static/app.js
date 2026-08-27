// OpenUnknown 前端逻辑：登录/注册 + 多会话管理 + 流式问答 + MCP 扩展 + 模型/模式 + ApiKey 设置
const LS_KEY = "openunknown:current_session";
const LS_TOKEN_KEY = "openunknown:token";
const LS_MODEL_KEY = "openunknown:model";
const LS_MODE_KEY = "openunknown:mode";

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const chatEl = document.getElementById("chat");
const sessionListEl = document.getElementById("sessionList");
const newBtn = document.getElementById("newBtn");
const modelSelect = document.getElementById("modelSelect");
const modeSelect = document.getElementById("modeSelect");

// 登录 / 注册相关 DOM
const authOverlay = document.getElementById("authOverlay");
const authLoginTab = document.getElementById("authLoginTab");
const authRegisterTab = document.getElementById("authRegisterTab");
const authForm = document.getElementById("authForm");
const authUsername = document.getElementById("authUsername");
const authPassword = document.getElementById("authPassword");
const authError = document.getElementById("authError");
const authSubmitBtn = document.getElementById("authSubmitBtn");
const userName = document.getElementById("userName");
const logoutBtn = document.getElementById("logoutBtn");
const gateBanner = document.getElementById("gateBanner");
const gateOpenSettingsBtn = document.getElementById("gateOpenSettingsBtn");

// MCP 相关 DOM 元素
const mcpModal = document.getElementById("mcpModal");
const openMcpModalBtn = document.getElementById("openMcpModalBtn");
const closeMcpModalBtn = document.getElementById("closeMcpModalBtn");
const mcpCountBadge = document.getElementById("mcpCountBadge");

const tabListBtn = document.getElementById("tabListBtn");
const tabFormBtn = document.getElementById("tabFormBtn");
const tabImportBtn = document.getElementById("tabImportBtn");

const paneList = document.getElementById("paneList");
const paneForm = document.getElementById("paneForm");
const paneImport = document.getElementById("paneImport");

const mcpServerList = document.getElementById("mcpServerList");
const mcpForm = document.getElementById("mcpForm");
const mcpFormId = document.getElementById("mcpFormId");
const mcpName = document.getElementById("mcpName");
const mcpType = document.getElementById("mcpType");
const stdioFields = document.getElementById("stdioFields");
const sseFields = document.getElementById("sseFields");
const mcpCommand = document.getElementById("mcpCommand");
const mcpArgs = document.getElementById("mcpArgs");
const mcpEnv = document.getElementById("mcpEnv");
const mcpUrl = document.getElementById("mcpUrl");
const testFormBtn = document.getElementById("testFormBtn");
const saveFormBtn = document.getElementById("saveFormBtn");
const testResultBox = document.getElementById("testResultBox");

const mcpJsonInput = document.getElementById("mcpJsonInput");
const doImportBtn = document.getElementById("doImportBtn");
const importResultBox = document.getElementById("importResultBox");

// 设置（模型服务 ApiKey）相关 DOM 元素
const settingsModal = document.getElementById("settingsModal");
const openSettingsBtn = document.getElementById("openSettingsBtn");
const closeSettingsModalBtn = document.getElementById("closeSettingsModalBtn");
const settingsStatusDot = document.getElementById("settingsStatusDot");
const platformSelect = document.getElementById("platformSelect");
const apiKeyInput = document.getElementById("apiKeyInput");
const toggleApiKeyBtn = document.getElementById("toggleApiKeyBtn");
const apiKeyStatus = document.getElementById("apiKeyStatus");
const testApiKeyBtn = document.getElementById("testApiKeyBtn");
const saveApiKeyBtn = document.getElementById("saveApiKeyBtn");
const clearApiKeyBtn = document.getElementById("clearApiKeyBtn");
const settingsResetRow = document.getElementById("settingsResetRow");
const apiKeyResultBox = document.getElementById("apiKeyResultBox");

// 状态
let authToken = localStorage.getItem(LS_TOKEN_KEY) || "";
let currentUser = null;
let authMode = "login";
let defaultPlatform = "bailian";
let busy = false;
let controller = null;
let currentSessionId = localStorage.getItem(LS_KEY) || newSessionId();
let mcpServersCache = [];
let currentModel = localStorage.getItem(LS_MODEL_KEY) || "";
let currentMode = localStorage.getItem(LS_MODE_KEY) || "";

function newSessionId() {
  return "sess-" + (crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36));
}

// 登录/退出时重置会话 id，避免不同用户复用同一本地会话 id
function resetSessionId() {
  currentSessionId = newSessionId();
  localStorage.setItem(LS_KEY, currentSessionId);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ===== 鉴权封装 =====
function setToken(t) {
  authToken = t || "";
  if (authToken) localStorage.setItem(LS_TOKEN_KEY, authToken);
  else localStorage.removeItem(LS_TOKEN_KEY);
}

async function apiFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (authToken) headers["Authorization"] = "Bearer " + authToken;
  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 401) {
    doLogout();
    throw new Error("登录已过期，请重新登录");
  }
  return resp;
}

function showAuth() { authOverlay.style.display = "flex"; }
function hideAuth() { authOverlay.style.display = "none"; }

function setAuthMode(mode) {
  authMode = mode;
  authLoginTab.classList.toggle("active", mode === "login");
  authRegisterTab.classList.toggle("active", mode === "register");
  authSubmitBtn.textContent = mode === "login" ? "登录" : "注册";
  authError.style.display = "none";
  authError.textContent = "";
}

function showAuthError(msg) {
  authError.textContent = msg;
  authError.style.display = "block";
}

function doLogout() {
  if (authToken) {
    fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Authorization": "Bearer " + authToken },
    }).catch(() => {});
  }
  setToken("");
  currentUser = null;
  userName.textContent = "未登录";
  resetSessionId();
  clearMessages();
  sessionListEl.innerHTML = "";
  mcpServerList.innerHTML = "";
  renderGate();
  showAuth();
}

// ===== 登录密码 RSA-OAEP 加密（请求体不传明文密码） =====
function pemToArrayBuffer(pem) {
  const b64 = pem.replace(/-----(BEGIN|END)[^-]+-----/g, "").replace(/\s+/g, "");
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

async function encryptPassword(publicKeyPem, password) {
  const key = await crypto.subtle.importKey(
    "spki",
    pemToArrayBuffer(publicKeyPem),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"]
  );
  const data = new TextEncoder().encode(password);
  // RSA-2048 + OAEP-SHA256 的最大明文长度是 190 字节
  if (data.length > 190) {
    throw new Error("密码过长");
  }
  const ciphertext = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, key, data);
  return arrayBufferToBase64(ciphertext);
}

authLoginTab.addEventListener("click", () => setAuthMode("login"));
authRegisterTab.addEventListener("click", () => setAuthMode("register"));

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = authUsername.value.trim();
  const password = authPassword.value;
  if (!username || !password) {
    showAuthError("请填写用户名和密码");
    return;
  }
  authSubmitBtn.disabled = true;
  try {
    // 先获取服务端 RSA 公钥与一次性 nonce，再加密密码
    const chalResp = await fetch("/api/auth/challenge");
    const chal = await chalResp.json();
    if (!chalResp.ok || !chal.nonce || !chal.public_key_pem) {
      showAuthError("获取登录校验信息失败，请重试");
      return;
    }
    const passwordCiphertext = await encryptPassword(chal.public_key_pem, password);
    const url = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        password_ciphertext: passwordCiphertext,
        nonce: chal.nonce,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showAuthError(data.detail || "操作失败");
      return;
    }
    setToken(data.token);
    currentUser = data.user;
    authPassword.value = "";
    resetSessionId();
    hideAuth();
    await bootstrapApp();
  } catch (err) {
    showAuthError("请求失败：" + err.message);
  } finally {
    authSubmitBtn.disabled = false;
  }
});

logoutBtn.addEventListener("click", doLogout);

// ===== 无 ApiKey 拦截 =====
function renderGate() {
  const hasKey = !!(currentUser && currentUser.has_api_key);
  gateBanner.style.display = hasKey ? "none" : "flex";
  inputEl.disabled = !hasKey;
  sendBtn.disabled = !hasKey;
  settingsStatusDot.className = "settings-status-dot" + (hasKey ? " on" : "");
  settingsStatusDot.title = hasKey ? "已配置 ApiKey" : "未配置 ApiKey";
}

gateOpenSettingsBtn.addEventListener("click", () => {
  settingsModal.style.display = "flex";
  apiKeyResultBox.style.display = "none";
  loadSettings();
});

// ===== 基础工具 =====
function setBusy(state) {
  busy = state;
  sendBtn.textContent = state ? "停止" : "发送";
  sendBtn.classList.toggle("stop", state);
}

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + "px";
}
inputEl.addEventListener("input", autoGrow);

function scrollToBottom() { chatEl.scrollTop = chatEl.scrollHeight; }

function clearMessages() {
  messagesEl.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.id = "empty";
  empty.innerHTML = "<h2>你好，我是 OpenUnknown</h2><div>有什么想问的，尽管开始吧。支持天气查询与自定义 MCP 工具。</div>";
  messagesEl.appendChild(empty);
}

function addMessage(role, text) {
  const e = document.getElementById("empty");
  if (e) e.remove();
  const msg = document.createElement("div");
  msg.className = "msg " + role;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "我" : "O";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  msg.appendChild(avatar);
  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  scrollToBottom();
  return bubble;
}

function addMeta(bubble, text, stopped) {
  const meta = document.createElement("div");
  meta.className = "meta" + (stopped ? " stopped" : "");
  meta.textContent = text;
  bubble.parentElement.appendChild(meta);
  scrollToBottom();
}

// ===== 会话管理 =====
async function loadSessions() {
  try {
    const resp = await apiFetch("/api/sessions");
    const data = await resp.json();
    renderSessions(data.sessions || []);
  } catch (e) {
    console.error("load sessions failed", e);
  }
}

function renderSessions(sessions) {
  sessionListEl.innerHTML = "";
  if (!sessions.length) {
    const tip = document.createElement("div");
    tip.style.cssText = "color:var(--muted);font-size:12px;padding:10px;text-align:center;";
    tip.textContent = "暂无历史对话";
    sessionListEl.appendChild(tip);
    return;
  }
  for (const s of sessions) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === currentSessionId ? " active" : "");
    item.dataset.id = s.id;
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = s.title || "新对话";
    const del = document.createElement("button");
    del.className = "del";
    del.title = "删除";
    del.textContent = "x";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteSession(s.id);
    });
    item.appendChild(title);
    item.appendChild(del);
    item.addEventListener("click", () => selectSession(s.id));
    sessionListEl.appendChild(item);
  }
}

async function selectSession(id) {
  if (busy) return;
  currentSessionId = id;
  localStorage.setItem(LS_KEY, id);
  clearMessages();
  document.querySelectorAll(".session-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === id);
  });
  try {
    const resp = await apiFetch("/api/sessions/" + id + "/messages");
    const data = await resp.json();
    for (const m of (data.messages || [])) {
      if (m.role === "system") continue;
      addMessage(m.role === "assistant" ? "bot" : "user", m.content);
    }
  } catch (e) {
    console.error("load messages failed", e);
  }
  inputEl.focus();
}

function newSession() {
  if (busy) return;
  currentSessionId = newSessionId();
  localStorage.setItem(LS_KEY, currentSessionId);
  clearMessages();
  document.querySelectorAll(".session-item").forEach((el) => el.classList.remove("active"));
  inputEl.focus();
}

async function deleteSession(id) {
  if (busy) return;
  if (!confirm("确定删除这个对话吗？")) return;
  try {
    await apiFetch("/api/sessions/" + id, { method: "DELETE" });
    if (id === currentSessionId) {
      currentSessionId = newSessionId();
      localStorage.setItem(LS_KEY, currentSessionId);
      clearMessages();
    }
    await loadSessions();
  } catch (e) {
    console.error("delete session failed", e);
  }
}

newBtn.addEventListener("click", newSession);

// ===== 发送逻辑 =====
async function send() {
  const text = inputEl.value.trim();
  if (!text || busy) return;
  setBusy(true);

  addMessage("user", text);
  inputEl.value = "";
  autoGrow();

  const traceEl = document.createElement("div");
  traceEl.className = "tool-trace";
  const e = document.getElementById("empty");
  if (e) e.remove();
  messagesEl.appendChild(traceEl);

  const bubble = addMessage("bot", "");
  bubble.classList.add("cursor-blink");
  let answer = "";
  let usage = null;
  let stopped = false;
  let usedModel = modelSelect.value || currentModel;
  let usedMode = modeSelect.value || currentMode;
  let thinking = "";
  let thinkEl = null;
  const toolBadges = {};

  controller = new AbortController();

  try {
    const resp = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: currentSessionId,
        model: modelSelect.value || currentModel,
        mode: modeSelect.value || currentMode,
      }),
      signal: controller.signal,
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]" || !data) continue;
        const payload = JSON.parse(data);
        if (payload.error) {
          bubble.classList.add("error");
          bubble.classList.remove("cursor-blink");
          bubble.textContent = "出错了：" + payload.error;
          continue;
        }
        if (payload.usage) { usage = payload.usage; continue; }
        if (payload.model) { usedModel = payload.model; continue; }
        if (payload.mode) { usedMode = payload.mode; continue; }

        if (payload.thinking) {
          thinking += payload.thinking;
          if (!thinkEl) {
            thinkEl = document.createElement("details");
            thinkEl.className = "thinking";
            const summary = document.createElement("summary");
            const body = document.createElement("div");
            body.className = "thinking-body";
            thinkEl.appendChild(summary);
            thinkEl.appendChild(body);
            messagesEl.insertBefore(thinkEl, traceEl);
          }
          const summary = thinkEl.querySelector("summary");
          summary.innerHTML = '<span class="thinking-dot"></span>思考过程<span class="thinking-hint">思考中…</span>';
          thinkEl.querySelector(".thinking-body").textContent = thinking;
          scrollToBottom();
          continue;
        }

        if (payload.tool_call) {
          const callId = payload.tool_call.id;
          const toolName = payload.tool_call.tool;
          if (toolBadges[callId]) { continue; }
          const badge = document.createElement("span");
          badge.className = "tool-badge calling";
          badge.innerHTML = `<span class="dot"></span> ${escapeHtml(toolName)} 调用中...`;
          traceEl.appendChild(badge);
          toolBadges[callId] = badge;
          scrollToBottom();
          continue;
        }

        if (payload.tool_result) {
          const callId = payload.tool_result.id;
          const toolName = payload.tool_result.tool;
          const badge = toolBadges[callId];
          if (badge) {
            badge.className = "tool-badge done";
            badge.title = payload.tool_result.output || "";
            badge.innerHTML = `<span class="dot"></span> ${escapeHtml(toolName)} 已返回`;
          } else {
            const newBadge = document.createElement("span");
            newBadge.className = "tool-badge done";
            newBadge.title = payload.tool_result.output || "";
            newBadge.innerHTML = `<span class="dot"></span> ${escapeHtml(toolName)} 已返回`;
            traceEl.appendChild(newBadge);
          }
          scrollToBottom();
          continue;
        }

        if (payload.delta) {
          if (thinkEl && !thinkEl.classList.contains("done")) {
            thinkEl.classList.add("done");
            thinkEl.querySelector("summary").innerHTML =
              '<span class="thinking-dot"></span>思考过程<span class="thinking-hint">已完成</span>';
          }
          answer += payload.delta;
          bubble.textContent = answer;
          scrollToBottom();
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      stopped = true;
    } else {
      bubble.classList.add("error");
      bubble.textContent = "请求失败：" + err.message;
    }
  } finally {
    bubble.classList.remove("cursor-blink");
    if (thinkEl && !thinkEl.classList.contains("done")) {
      thinkEl.classList.add("done");
      thinkEl.querySelector("summary").innerHTML =
        '<span class="thinking-dot"></span>思考过程<span class="thinking-hint">' +
        (stopped ? "已停止" : "已完成") + "</span>";
    }
    if (!traceEl.children.length) traceEl.remove();
    if (stopped) {
      addMeta(bubble, "已停止生成", true);
    } else if (usage) {
      const modelHint = usedModel ? "模型 " + usedModel + " · " : "";
      let modeHint = "";
      if (usedMode && usedMode !== "fast") {
        const opt = modeSelect.querySelector('option[value="' + usedMode + '"]');
        if (opt) modeHint = opt.textContent + " · ";
      }
      addMeta(bubble, modeHint + modelHint + "本轮 Tokens：输入 " + usage.input_tokens + " · 输出 " + usage.output_tokens + " · 合计 " + usage.total_tokens, false);
    }
    controller = null;
    setBusy(false);
    loadSessions();
    inputEl.focus();
  }
}

function onSendClick() {
  if (busy) {
    if (controller) controller.abort();
  } else {
    send();
  }
}

sendBtn.addEventListener("click", onSendClick);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

// ===== MCP 扩展交互逻辑 =====
function switchMcpTab(tabName) {
  tabListBtn.classList.toggle("active", tabName === "list");
  tabFormBtn.classList.toggle("active", tabName === "form");
  tabImportBtn.classList.toggle("active", tabName === "import");

  paneList.style.display = tabName === "list" ? "block" : "none";
  paneForm.style.display = tabName === "form" ? "block" : "none";
  paneImport.style.display = tabName === "import" ? "block" : "none";

  testResultBox.style.display = "none";
  importResultBox.style.display = "none";
}

tabListBtn.addEventListener("click", () => switchMcpTab("list"));
tabFormBtn.addEventListener("click", () => {
  resetMcpForm();
  switchMcpTab("form");
});
tabImportBtn.addEventListener("click", () => switchMcpTab("import"));

openMcpModalBtn.addEventListener("click", () => {
  mcpModal.style.display = "flex";
  switchMcpTab("list");
  loadMcpServers();
});

closeMcpModalBtn.addEventListener("click", () => {
  mcpModal.style.display = "none";
});

mcpModal.addEventListener("click", (e) => {
  if (e.target === mcpModal) mcpModal.style.display = "none";
});

mcpType.addEventListener("change", () => {
  const isStdio = mcpType.value === "stdio";
  stdioFields.style.display = isStdio ? "block" : "none";
  sseFields.style.display = isStdio ? "none" : "block";
});

function resetMcpForm() {
  mcpForm.reset();
  mcpFormId.value = "";
  mcpType.value = "stdio";
  stdioFields.style.display = "block";
  sseFields.style.display = "none";
  tabFormBtn.textContent = "+ 添加服务";
  testResultBox.style.display = "none";
}

function getFormData() {
  const id = mcpFormId.value.trim() || undefined;
  const name = mcpName.value.trim();
  const server_type = mcpType.value;
  let args = [];
  let env = {};

  if (server_type === "stdio") {
    const rawArgs = mcpArgs.value.trim();
    if (rawArgs) {
      args = rawArgs.includes("\n")
        ? rawArgs.split("\n").map(s => s.trim()).filter(Boolean)
        : rawArgs.split(/\s+/).filter(Boolean);
    }
    const rawEnv = mcpEnv.value.trim();
    if (rawEnv) {
      try {
        env = JSON.parse(rawEnv);
      } catch (err) {
        throw new Error("环境变量格式必须为合法 JSON 字典，例如: {\"KEY\": \"VALUE\"}");
      }
    }
  }

  return {
    id,
    name,
    server_type,
    command: server_type === "stdio" ? mcpCommand.value.trim() : null,
    args,
    env,
    url: server_type === "sse" ? mcpUrl.value.trim() : null,
    enabled: true,
  };
}

async function loadMcpServers() {
  try {
    const resp = await apiFetch("/api/mcp/servers");
    const data = await resp.json();
    mcpServersCache = data.servers || [];
    renderMcpServers(mcpServersCache);
  } catch (err) {
    console.error("加载 MCP 服务器失败", err);
  }
}

function renderMcpServers(servers) {
  const enabledCount = servers.filter(s => s.enabled).length;
  mcpCountBadge.textContent = `${enabledCount}/${servers.length}`;

  mcpServerList.innerHTML = "";
  if (!servers.length) {
    mcpServerList.innerHTML = '<div class="mcp-empty-tip">暂无配置的 MCP Server，点击上方「+ 添加服务」或「JSON 导入」添加。</div>';
    return;
  }

  for (const s of servers) {
    const card = document.createElement("div");
    card.className = "mcp-card";

    const cmdText = s.server_type === "stdio"
      ? `${s.command} ${(s.args || []).join(" ")}`
      : s.url;

    card.innerHTML = `
      <div class="mcp-card-head">
        <div class="mcp-card-title">
          <span>${escapeHtml(s.name)}</span>
          <span class="mcp-type-tag">${s.server_type}</span>
        </div>
        <div class="mcp-card-actions">
          <label class="switch" title="启用/禁用">
            <input type="checkbox" ${s.enabled ? "checked" : ""} data-id="${s.id}" class="mcp-toggle-cb" />
            <span class="slider"></span>
          </label>
          <button class="btn-icon" data-action="test" data-id="${s.id}" title="测试连接并查看工具">测试</button>
          <button class="btn-icon" data-action="edit" data-id="${s.id}" title="编辑">编辑</button>
          <button class="btn-icon del" data-action="delete" data-id="${s.id}" title="删除">删除</button>
        </div>
      </div>
      <div class="mcp-card-cmd">${escapeHtml(cmdText)}</div>
      <div class="mcp-card-tools" id="toolsPreview_${s.id}"></div>
    `;

    const toggleCb = card.querySelector(".mcp-toggle-cb");
    toggleCb.addEventListener("change", async (e) => {
      await toggleMcp(s.id, e.target.checked);
    });

    const testBtn = card.querySelector('[data-action="test"]');
    testBtn.addEventListener("click", () => testAndPreviewMcp(s));

    const editBtn = card.querySelector('[data-action="edit"]');
    editBtn.addEventListener("click", () => editMcp(s));

    const delBtn = card.querySelector('[data-action="delete"]');
    delBtn.addEventListener("click", () => deleteMcp(s.id, s.name));

    mcpServerList.appendChild(card);
  }
}

async function toggleMcp(id, enabled) {
  try {
    await apiFetch(`/api/mcp/servers/${id}/toggle`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    await loadMcpServers();
  } catch (err) {
    alert("切换状态失败: " + err.message);
  }
}

async function deleteMcp(id, name) {
  if (!confirm(`确定删除 MCP 服务「${name}」吗？`)) return;
  try {
    await apiFetch(`/api/mcp/servers/${id}`, { method: "DELETE" });
    await loadMcpServers();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

function editMcp(s) {
  mcpFormId.value = s.id;
  mcpName.value = s.name;
  mcpType.value = s.server_type;
  mcpCommand.value = s.command || "";
  mcpArgs.value = (s.args || []).join("\n");
  mcpEnv.value = Object.keys(s.env || {}).length ? JSON.stringify(s.env, null, 2) : "";
  mcpUrl.value = s.url || "";

  mcpType.dispatchEvent(new Event("change"));
  tabFormBtn.textContent = "编辑服务";
  switchMcpTab("form");
}

async function testAndPreviewMcp(s) {
  const container = document.getElementById(`toolsPreview_${s.id}`);
  if (container) {
    container.innerHTML = '<span style="color:var(--accent);">连接测试中...</span>';
  }
  try {
    const resp = await apiFetch("/api/mcp/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
    });
    const res = await resp.json();
    if (container) {
      if (res.ok) {
        if (!res.tools || !res.tools.length) {
          container.innerHTML = '<span style="color:var(--muted);">连接成功 (未暴露任何 Tools)</span>';
        } else {
          container.innerHTML = res.tools.map(t =>
            `<span class="mcp-tool-pill" title="${escapeHtml(t.description || '')}">${escapeHtml(t.name)}</span>`
          ).join("");
        }
      } else {
        container.innerHTML = `<span style="color:var(--red);">连接失败: ${escapeHtml(res.error)}</span>`;
      }
    }
  } catch (err) {
    if (container) {
      container.innerHTML = `<span style="color:var(--red);">测试失败: ${escapeHtml(err.message)}</span>`;
    }
  }
}

testFormBtn.addEventListener("click", async () => {
  testResultBox.style.display = "block";
  testResultBox.className = "test-result-box";
  testResultBox.textContent = "正在测试连接 MCP Server...";
  testFormBtn.disabled = true;

  try {
    const data = getFormData();
    const resp = await apiFetch("/api/mcp/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const res = await resp.json();
    if (res.ok) {
      testResultBox.className = "test-result-box success";
      const count = res.tools ? res.tools.length : 0;
      let text = `连接成功！共获取到 ${count} 个工具：\n`;
      if (res.tools) {
        text += res.tools.map(t => `• ${t.name}: ${t.description || "无描述"}`).join("\n");
      }
      testResultBox.textContent = text;
    } else {
      testResultBox.className = "test-result-box error";
      testResultBox.textContent = `连接失败: ${res.error}`;
    }
  } catch (err) {
    testResultBox.className = "test-result-box error";
    testResultBox.textContent = `错误: ${err.message}`;
  } finally {
    testFormBtn.disabled = false;
  }
});

mcpForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  saveFormBtn.disabled = true;
  try {
    const data = getFormData();
    const resp = await apiFetch("/api/mcp/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const res = await resp.json();
    if (res.server) {
      await loadMcpServers();
      switchMcpTab("list");
      resetMcpForm();
    } else {
      alert("保存失败");
    }
  } catch (err) {
    alert("保存失败: " + err.message);
  } finally {
    saveFormBtn.disabled = false;
  }
});

doImportBtn.addEventListener("click", async () => {
  const text = mcpJsonInput.value.trim();
  if (!text) return;
  importResultBox.style.display = "block";
  importResultBox.className = "test-result-box";
  importResultBox.textContent = "正在解析并导入...";

  try {
    const parsed = JSON.parse(text);
    const resp = await apiFetch("/api/mcp/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: parsed }),
    });
    const res = await resp.json();
    if (res.ok) {
      importResultBox.className = "test-result-box success";
      importResultBox.textContent = `导入成功！共添加/更新 ${res.imported_count} 个 MCP 服务。`;
      mcpJsonInput.value = "";
      await loadMcpServers();
      setTimeout(() => switchMcpTab("list"), 1200);
    } else {
      importResultBox.className = "test-result-box error";
      importResultBox.textContent = `导入失败: ${res.detail || "未知错误"}`;
    }
  } catch (err) {
    importResultBox.className = "test-result-box error";
    importResultBox.textContent = `JSON 解析错误: ${err.message}`;
  }
});

// ===== 模型服务设置（ApiKey） =====
function showApiKeyResult(message, kind) {
  apiKeyResultBox.style.display = "block";
  apiKeyResultBox.className = "test-result-box" + (kind ? " " + kind : "");
  apiKeyResultBox.textContent = message;
}

function renderApiKeyStatus(data) {
  const platforms = data.platforms || [];
  const def = data.default_platform || "bailian";
  defaultPlatform = def;

  platformSelect.innerHTML = "";
  for (const p of platforms) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    if (p.id === def) opt.selected = true;
    platformSelect.appendChild(opt);
  }

  const cur = data.current || {};
  const hasKey = !!cur.has_key;
  if (currentUser) currentUser.has_api_key = hasKey;

  settingsResetRow.style.display = hasKey ? "block" : "none";
  apiKeyInput.value = "";
  apiKeyStatus.textContent = hasKey
    ? "当前已配置 · " + (cur.key_masked || "")
    : "尚未配置 ApiKey，请填写并保存";
  renderGate();
}

async function loadSettings() {
  try {
    const resp = await apiFetch("/api/settings");
    const data = await resp.json();
    renderApiKeyStatus(data);
  } catch (err) {
    console.error("加载设置失败", err);
  }
}

openSettingsBtn.addEventListener("click", () => {
  settingsModal.style.display = "flex";
  apiKeyResultBox.style.display = "none";
  loadSettings();
});

closeSettingsModalBtn.addEventListener("click", () => {
  settingsModal.style.display = "none";
});

settingsModal.addEventListener("click", (e) => {
  if (e.target === settingsModal) settingsModal.style.display = "none";
});

toggleApiKeyBtn.addEventListener("click", () => {
  const isPassword = apiKeyInput.type === "password";
  apiKeyInput.type = isPassword ? "text" : "password";
  toggleApiKeyBtn.textContent = isPassword ? "隐藏" : "显示";
});

testApiKeyBtn.addEventListener("click", async () => {
  const key = apiKeyInput.value.trim();
  if (!key) {
    showApiKeyResult("请输入 ApiKey 后再测试", "error");
    return;
  }
  showApiKeyResult("正在测试连接...", "");
  testApiKeyBtn.disabled = true;
  try {
    const resp = await apiFetch("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, platform: platformSelect.value }),
    });
    const res = await resp.json();
    showApiKeyResult(
      res.ok ? "连接成功，ApiKey 可用" : "连接失败: " + (res.error || "未知错误"),
      res.ok ? "success" : "error"
    );
  } catch (err) {
    showApiKeyResult("测试失败: " + err.message, "error");
  } finally {
    testApiKeyBtn.disabled = false;
  }
});

saveApiKeyBtn.addEventListener("click", async () => {
  const key = apiKeyInput.value.trim();
  if (!key) {
    showApiKeyResult("请输入 ApiKey", "error");
    return;
  }
  saveApiKeyBtn.disabled = true;
  try {
    const resp = await apiFetch("/api/settings/api-key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, platform: platformSelect.value }),
    });
    const res = await resp.json();
    if (res.ok) {
      showApiKeyResult("已加密保存并生效", "success");
      await loadSettings();
      setTimeout(() => { settingsModal.style.display = "none"; }, 600);
    } else {
      showApiKeyResult("保存失败: " + (res.detail || "未知错误"), "error");
    }
  } catch (err) {
    showApiKeyResult("保存失败: " + err.message, "error");
  } finally {
    saveApiKeyBtn.disabled = false;
  }
});

clearApiKeyBtn.addEventListener("click", async () => {
  if (!confirm("确定清除已保存的 ApiKey 吗？清除后将无法使用对话功能。")) return;
  try {
    const resp = await apiFetch(
      "/api/settings/api-key?platform=" + encodeURIComponent(platformSelect.value),
      { method: "DELETE" }
    );
    const res = await resp.json();
    if (res.ok) {
      apiKeyInput.value = "";
      showApiKeyResult("已清除 ApiKey", "success");
      await loadSettings();
    } else {
      showApiKeyResult("清除失败", "error");
    }
  } catch (err) {
    showApiKeyResult("清除失败: " + err.message, "error");
  }
});

// ===== 模型选择 =====
async function loadModels() {
  try {
    const resp = await apiFetch("/api/models");
    const data = await resp.json();
    const models = data.models || [];
    if (!models.some((m) => m.id === currentModel)) {
      currentModel = data.default || (models[0] && models[0].id) || "";
    }
    modelSelect.innerHTML = "";
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.name;
      if (m.id === currentModel) opt.selected = true;
      modelSelect.appendChild(opt);
    }
    localStorage.setItem(LS_MODEL_KEY, currentModel);
  } catch (e) {
    console.error("load models failed", e);
  }
}

modelSelect.addEventListener("change", () => {
  currentModel = modelSelect.value;
  localStorage.setItem(LS_MODEL_KEY, currentModel);
});

// ===== 模式选择 =====
async function loadModes() {
  try {
    const resp = await apiFetch("/api/modes");
    const data = await resp.json();
    const modes = data.modes || [];
    if (!modes.some((m) => m.id === currentMode)) {
      currentMode = data.default || (modes[0] && modes[0].id) || "";
    }
    modeSelect.innerHTML = "";
    for (const m of modes) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.name;
      if (m.id === currentMode) opt.selected = true;
      modeSelect.appendChild(opt);
    }
    localStorage.setItem(LS_MODE_KEY, currentMode);
  } catch (e) {
    console.error("load modes failed", e);
  }
}

modeSelect.addEventListener("change", () => {
  currentMode = modeSelect.value;
  localStorage.setItem(LS_MODE_KEY, currentMode);
});

// ===== 应用启动 =====
async function bootstrapApp() {
  try {
    const resp = await apiFetch("/api/auth/me");
    if (!resp.ok) throw new Error("未登录");
    currentUser = await resp.json();
    userName.textContent = currentUser.username;
    await loadModes();
    await loadModels();
    await loadSessions();
    await loadMcpServers();
    await loadSettings();
    renderGate();
    const exists = document.querySelector('.session-item[data-id="' + currentSessionId + '"]');
    if (exists) {
      await selectSession(currentSessionId);
    } else {
      inputEl.focus();
    }
  } catch (e) {
    doLogout();
  }
}

(async function init() {
  if (!authToken) {
    showAuth();
    return;
  }
  try {
    const resp = await apiFetch("/api/auth/me");
    if (!resp.ok) throw new Error("未登录");
    currentUser = await resp.json();
    userName.textContent = currentUser.username;
    hideAuth();
    await loadModes();
    await loadModels();
    await loadSessions();
    await loadMcpServers();
    await loadSettings();
    renderGate();
    const exists = document.querySelector('.session-item[data-id="' + currentSessionId + '"]');
    if (exists) {
      await selectSession(currentSessionId);
    } else {
      inputEl.focus();
    }
  } catch (e) {
    showAuth();
  }
})();
