// OpenUnknown 前端逻辑：多会话管理 + 流式问答 + MCP 扩展管理 + 模型选择
const LS_KEY = "openunknown:current_session";
const LS_MODEL_KEY = "openunknown:model";
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const chatEl = document.getElementById("chat");
const sessionListEl = document.getElementById("sessionList");
const newBtn = document.getElementById("newBtn");
const modelSelect = document.getElementById("modelSelect");

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

let busy = false;
let controller = null;
let currentSessionId = localStorage.getItem(LS_KEY) || newSessionId();
let mcpServersCache = [];
let currentModel = localStorage.getItem(LS_MODEL_KEY) || "";

function newSessionId() {
  return "sess-" + (crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36));
}

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
    const resp = await fetch("/api/sessions");
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
    const resp = await fetch("/api/sessions/" + id + "/messages");
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
    await fetch("/api/sessions/" + id, { method: "DELETE" });
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

  // 工具调用透明化：在 bot 气泡上方插入 trace 容器
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
  // 记录每个工具 badge 节点，key 为 tool_call_id（同名工具可能并发多次调用）
  const toolBadges = {};

  controller = new AbortController();

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: currentSessionId, model: modelSelect.value || currentModel }),
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

        // 工具调用开始：创建 calling 状态的 badge，按 id 去重
        if (payload.tool_call) {
          const callId = payload.tool_call.id;
          const toolName = payload.tool_call.tool;
          if (toolBadges[callId]) { continue; } // 同一调用重复到达则跳过
          const badge = document.createElement("span");
          badge.className = "tool-badge calling";
          badge.innerHTML = `<span class="dot"></span> ${escapeHtml(toolName)} 调用中...`;
          traceEl.appendChild(badge);
          toolBadges[callId] = badge;
          scrollToBottom();
          continue;
        }

        // 工具结果返回：按 id 找到对应 badge 更新为 done
        if (payload.tool_result) {
          const callId = payload.tool_result.id;
          const toolName = payload.tool_result.tool;
          const badge = toolBadges[callId];
          if (badge) {
            badge.className = "tool-badge done";
            badge.title = payload.tool_result.output || "";
            badge.innerHTML = `<span class="dot"></span> ${escapeHtml(toolName)} 已返回`;
          } else {
            // 没有对应的 calling badge 时（工具节点先到），补一个
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
    // 没有任何工具调用时移除空 trace 容器，避免占用间距
    if (!traceEl.children.length) traceEl.remove();
    if (stopped) {
      addMeta(bubble, "已停止生成", true);
    } else if (usage) {
      const modelHint = usedModel ? "模型 " + usedModel + " · " : "";
      addMeta(bubble, modelHint + "本轮 Tokens：输入 " + usage.input_tokens + " · 输出 " + usage.output_tokens + " · 合计 " + usage.total_tokens, false);
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
    const resp = await fetch("/api/mcp/servers");
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

    // 绑定事件
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

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function toggleMcp(id, enabled) {
  try {
    await fetch(`/api/mcp/servers/${id}/toggle`, {
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
    await fetch(`/api/mcp/servers/${id}`, { method: "DELETE" });
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
    const resp = await fetch("/api/mcp/test", {
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
    const resp = await fetch("/api/mcp/test", {
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
    const resp = await fetch("/api/mcp/servers", {
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
    const resp = await fetch("/api/mcp/import", {
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

// ===== 模型选择 =====
async function loadModels() {
  try {
    const resp = await fetch("/api/models");
    const data = await resp.json();
    const models = data.models || [];
    // 本地保存的模型若已失效则回退到后端默认模型
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

// ===== 初始化 =====
(async function init() {
  await loadModels();
  await loadSessions();
  await loadMcpServers();
  const exists = document.querySelector('.session-item[data-id="' + currentSessionId + '"]');
  if (exists) {
    await selectSession(currentSessionId);
  } else {
    inputEl.focus();
  }
})();
