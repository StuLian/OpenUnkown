import { useEffect, useState, type FormEvent } from "react";
import {
  deleteMcpServerRequest,
  importMcpRequest,
  saveMcpServer,
  testMcpRequest,
  toggleMcpServerRequest,
  type McpServerPayload,
} from "../api/endpoints";
import type { McpServer, McpServerType, McpTool } from "../types";
import Modal from "./Modal";

type Tab = "list" | "form" | "import";

interface McpFormState {
  id: string;
  name: string;
  server_type: McpServerType;
  command: string;
  args: string;
  env: string;
  url: string;
}

const EMPTY_FORM: McpFormState = {
  id: "",
  name: "",
  server_type: "stdio",
  command: "",
  args: "",
  env: "",
  url: "",
};

type Result = { kind: "" | "success" | "error"; text: string } | null;

interface Preview {
  loading: boolean;
  tools?: McpTool[];
  error?: string;
}

function toPayload(form: McpFormState): McpServerPayload {
  let args: string[] = [];
  let env: Record<string, string> = {};

  if (form.server_type === "stdio") {
    const rawArgs = form.args.trim();
    if (rawArgs) {
      args = rawArgs.includes("\n")
        ? rawArgs
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean)
        : rawArgs.split(/\s+/).filter(Boolean);
    }
    const rawEnv = form.env.trim();
    if (rawEnv) {
      try {
        env = JSON.parse(rawEnv);
      } catch {
        throw new Error('环境变量格式必须为合法 JSON 字典，例如: {"KEY": "VALUE"}');
      }
    }
  }

  return {
    id: form.id || undefined,
    name: form.name,
    server_type: form.server_type,
    command: form.server_type === "stdio" ? form.command.trim() : null,
    args,
    env,
    url: form.server_type === "sse" ? form.url.trim() : null,
    enabled: true,
  };
}

function serverToPayload(s: McpServer): McpServerPayload {
  return {
    id: s.id,
    name: s.name,
    server_type: s.server_type,
    command: s.command,
    args: s.args ?? [],
    env: s.env ?? {},
    url: s.url,
    enabled: s.enabled,
  };
}

interface McpModalProps {
  open: boolean;
  onClose: () => void;
  servers: McpServer[];
  onChanged: () => void;
}

export default function McpModal({
  open,
  onClose,
  servers,
  onChanged,
}: McpModalProps) {
  const [tab, setTab] = useState<Tab>("list");
  const [form, setForm] = useState<McpFormState>(EMPTY_FORM);
  const [formResult, setFormResult] = useState<Result>(null);
  const [importText, setImportText] = useState("");
  const [importResult, setImportResult] = useState<Result>(null);
  const [previews, setPreviews] = useState<Record<string, Preview>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (open) {
      setTab("list");
      setForm(EMPTY_FORM);
      setFormResult(null);
      setImportResult(null);
    }
  }, [open]);

  function setField<K extends keyof McpFormState>(
    key: K,
    value: McpFormState[K]
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function openAddForm() {
    setForm(EMPTY_FORM);
    setFormResult(null);
    setTab("form");
  }

  function openEditForm(s: McpServer) {
    setForm({
      id: s.id,
      name: s.name,
      server_type: s.server_type,
      command: s.command ?? "",
      args: (s.args ?? []).join("\n"),
      env: Object.keys(s.env ?? {}).length ? JSON.stringify(s.env, null, 2) : "",
      url: s.url ?? "",
    });
    setFormResult(null);
    setTab("form");
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = toPayload(form);
      await saveMcpServer(payload);
      onChanged();
      setTab("list");
      setForm(EMPTY_FORM);
    } catch (err) {
      alert("保存失败: " + (err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleFormTest() {
    setTesting(true);
    setFormResult({ kind: "", text: "正在测试连接 MCP Server..." });
    try {
      const payload = toPayload(form);
      const res = await testMcpRequest(payload);
      if (res.ok) {
        const count = res.tools ? res.tools.length : 0;
        const lines = (res.tools ?? [])
          .map((t) => `• ${t.name}: ${t.description || "无描述"}`)
          .join("\n");
        setFormResult({
          kind: "success",
          text: `连接成功！共获取到 ${count} 个工具：\n${lines}`,
        });
      } else {
        setFormResult({
          kind: "error",
          text: `连接失败: ${res.error}`,
        });
      }
    } catch (err) {
      setFormResult({ kind: "error", text: `错误: ${(err as Error).message}` });
    } finally {
      setTesting(false);
    }
  }

  async function handleImport() {
    const text = importText.trim();
    if (!text) return;
    setImportResult({ kind: "", text: "正在解析并导入..." });
    try {
      const parsed = JSON.parse(text);
      const res = await importMcpRequest(parsed);
      setImportResult({
        kind: "success",
        text: `导入成功！共添加/更新 ${res.imported_count} 个 MCP 服务。`,
      });
      setImportText("");
      onChanged();
      setTimeout(() => setTab("list"), 1200);
    } catch (err) {
      setImportResult({
        kind: "error",
        text: `JSON 解析错误: ${(err as Error).message}`,
      });
    }
  }

  async function handleToggle(s: McpServer, enabled: boolean) {
    try {
      await toggleMcpServerRequest(s.id, enabled);
      onChanged();
    } catch (err) {
      alert("切换状态失败: " + (err as Error).message);
    }
  }

  async function handleDelete(s: McpServer) {
    if (!confirm(`确定删除 MCP 服务「${s.name}」吗？`)) return;
    try {
      await deleteMcpServerRequest(s.id);
      onChanged();
    } catch (err) {
      alert("删除失败: " + (err as Error).message);
    }
  }

  async function handlePreview(s: McpServer) {
    setPreviews((prev) => ({ ...prev, [s.id]: { loading: true } }));
    try {
      const res = await testMcpRequest(serverToPayload(s));
      setPreviews((prev) => ({
        ...prev,
        [s.id]: { loading: false, tools: res.tools, error: res.ok ? undefined : res.error },
      }));
    } catch (err) {
      setPreviews((prev) => ({
        ...prev,
        [s.id]: { loading: false, error: (err as Error).message },
      }));
    }
  }

  const isEditing = !!form.id;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="MCP 扩展配置"
      subtitle="Model Context Protocol 客户端管理"
    >
      <div className="mcp-tabs">
        <button
          className={"mcp-tab" + (tab === "list" ? " active" : "")}
          onClick={() => setTab("list")}
        >
          已配置服务
        </button>
        <button
          className={"mcp-tab" + (tab === "form" ? " active" : "")}
          onClick={openAddForm}
        >
          {isEditing ? "编辑服务" : "+ 添加服务"}
        </button>
        <button
          className={"mcp-tab" + (tab === "import" ? " active" : "")}
          onClick={() => setTab("import")}
        >
          JSON 导入
        </button>
      </div>

      {tab === "list" ? (
        <div className="mcp-server-list">
          {servers.length === 0 ? (
            <div className="mcp-empty-tip">
              暂无配置的 MCP Server，点击上方「+ 添加服务」或「JSON 导入」添加。
            </div>
          ) : (
            servers.map((s) => {
              const cmdText =
                s.server_type === "stdio"
                  ? `${s.command} ${(s.args ?? []).join(" ")}`.trim()
                  : s.url ?? "";
              const preview = previews[s.id];
              return (
                <div className="mcp-card" key={s.id}>
                  <div className="mcp-card-head">
                    <div className="mcp-card-title">
                      <span>{s.name}</span>
                      <span className="mcp-type-tag">{s.server_type}</span>
                    </div>
                    <div className="mcp-card-actions">
                      <label className="switch" title="启用/禁用">
                        <input
                          type="checkbox"
                          checked={s.enabled}
                          onChange={(e) => void handleToggle(s, e.target.checked)}
                        />
                        <span className="slider" />
                      </label>
                      <button
                        className="btn-icon"
                        title="测试连接并查看工具"
                        onClick={() => void handlePreview(s)}
                      >
                        测试
                      </button>
                      <button
                        className="btn-icon"
                        title="编辑"
                        onClick={() => openEditForm(s)}
                      >
                        编辑
                      </button>
                      <button
                        className="btn-icon del"
                        title="删除"
                        onClick={() => void handleDelete(s)}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                  <div className="mcp-card-cmd">{cmdText}</div>
                  <div className="mcp-card-tools">
                    {preview?.loading ? (
                      <span style={{ color: "var(--accent)" }}>
                        连接测试中...
                      </span>
                    ) : preview?.error ? (
                      <span style={{ color: "var(--red)" }}>
                        连接失败: {preview.error}
                      </span>
                    ) : preview?.tools && preview.tools.length === 0 ? (
                      <span style={{ color: "var(--muted)" }}>
                        连接成功 (未暴露任何 Tools)
                      </span>
                    ) : (
                      (preview?.tools ?? []).map((t) => (
                        <span
                          className="mcp-tool-pill"
                          key={t.name}
                          title={t.description ?? ""}
                        >
                          {t.name}
                        </span>
                      ))
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      ) : null}

      {tab === "form" ? (
        <form className="mcp-form" onSubmit={handleSave}>
          <div className="form-row">
            <label>
              服务名称 <span className="req">*</span>
            </label>
            <input
              type="text"
              placeholder="例如: filesystem / github / memory"
              value={form.name}
              onChange={(e) => setField("name", e.target.value)}
              required
            />
          </div>

          <div className="form-row">
            <label>连接类型</label>
            <select
              value={form.server_type}
              onChange={(e) =>
                setField("server_type", e.target.value as McpServerType)
              }
            >
              <option value="stdio">stdio (本地命令行进程)</option>
              <option value="sse">sse / http (远程服务)</option>
            </select>
          </div>

          {form.server_type === "stdio" ? (
            <>
              <div className="form-row">
                <label>
                  执行命令 (Command) <span className="req">*</span>
                </label>
                <input
                  type="text"
                  placeholder="例如: npx / python / uvx"
                  value={form.command}
                  onChange={(e) => setField("command", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label>命令参数 (每行一个或空格分隔)</label>
                <textarea
                  rows={2}
                  placeholder={
                    "-y\n@modelcontextprotocol/server-filesystem\n/Users/username/Desktop"
                  }
                  value={form.args}
                  onChange={(e) => setField("args", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label>环境变量 (JSON 键值对，可选)</label>
                <textarea
                  rows={2}
                  placeholder='{"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"}'
                  value={form.env}
                  onChange={(e) => setField("env", e.target.value)}
                />
              </div>
            </>
          ) : (
            <div className="form-row">
              <label>
                Server URL <span className="req">*</span>
              </label>
              <input
                type="text"
                placeholder="http://localhost:8080/sse"
                value={form.url}
                onChange={(e) => setField("url", e.target.value)}
              />
            </div>
          )}

          <div className="form-actions">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={testing}
              onClick={() => void handleFormTest()}
            >
              测试连接
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving}
            >
              保存服务
            </button>
          </div>

          {formResult ? (
            <div
              className={
                "test-result-box" +
                (formResult.kind ? " " + formResult.kind : "")
              }
              style={{ whiteSpace: "pre-wrap" }}
            >
              {formResult.text}
            </div>
          ) : null}
        </form>
      ) : null}

      {tab === "import" ? (
        <>
          <div className="import-intro">
            支持直接粘贴 Claude Desktop / Cursor 的{" "}
            <code>claude_desktop_config.json</code> 中的{" "}
            <code>mcpServers</code> 配置：
          </div>
          <textarea
            className="json-textarea"
            rows={10}
            placeholder={
              '{\n  "mcpServers": {\n    "sqlite": {\n      "command": "uvx",\n      "args": ["mcp-server-sqlite", "--db-path", "/path/to/db.sqlite"]\n    }\n  }\n}'
            }
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
          />
          <div className="form-actions" style={{ marginTop: 14 }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleImport()}
            >
              一键导入并保存
            </button>
          </div>
          {importResult ? (
            <div
              className={
                "test-result-box" +
                (importResult.kind ? " " + importResult.kind : "")
              }
            >
              {importResult.text}
            </div>
          ) : null}
        </>
      ) : null}
    </Modal>
  );
}
