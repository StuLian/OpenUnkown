import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import {
  fetchFileLimits,
  fetchSessionMessages,
  uploadFile,
} from "../api/endpoints";
import { readSseStream } from "../lib/sse";
import Markdown from "./Markdown";
import type { Attachment, FileLimits, ModeOption, Usage } from "../types";

interface ToolCall {
  id: string;
  name: string;
  status: "calling" | "done";
  output?: string;
}

type ThinkingStatus = "thinking" | "done" | "stopped";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: boolean;
  stopped?: boolean;
  meta?: string;
  streaming?: boolean;
  thinking?: string;
  thinkingStatus?: ThinkingStatus;
  toolCalls?: ToolCall[];
}

function uid(prefix: string): string {
  return (
    prefix +
    "-" +
    (crypto.randomUUID
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36))
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function buildMeta(
  usedModel: string,
  usedMode: string,
  usage: Usage | null,
  stopped: boolean,
  modeName: string
): string | undefined {
  if (stopped) return "已停止生成";
  if (!usage) return undefined;
  const modelHint = usedModel ? `模型 ${usedModel} · ` : "";
  const modeHint =
    usedMode && usedMode !== "fast" && modeName ? `${modeName} · ` : "";
  return `${modeHint}${modelHint}本轮 Tokens：输入 ${usage.input_tokens} · 输出 ${usage.output_tokens} · 合计 ${usage.total_tokens}`;
}

interface UseChatOptions {
  sessionId: string;
  model: string;
  mode: string;
  modes: ModeOption[];
  limits: FileLimits | null;
  onSettled?: () => void;
}

function useChat({
  sessionId,
  model,
  mode,
  modes,
  limits,
  onSettled,
}: UseChatOptions) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;

  // 切换会话时中止进行中的生成，并载入历史消息。
  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setBusy(false);
    setInput("");
    setMessages([]);

    let cancelled = false;
    (async () => {
      try {
        const data = await fetchSessionMessages(sessionId);
        if (cancelled) return;
        setMessages(
          data.messages.map((m) => {
            const msg: Message = {
              id: uid("hist"),
              role: m.role,
              content: m.content,
            };
            if (m.role === "assistant" && m.usage) {
              msg.meta =
                "本轮 Tokens：输入 " +
                m.usage.input_tokens +
                " · 输出 " +
                m.usage.output_tokens +
                " · 合计 " +
                m.usage.total_tokens;
            }
            return msg;
          })
        );
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // 上传并解析文件，成功后将解析结果挂到附件列表。
  const attachFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;
      setUploading(true);
      setUploadError(null);
      try {
        for (const f of list) {
          // 本地预校验：扩展名 + 大小（后端仍会兜底校验）
          const ext = (f.name.split(".").pop() || "").toLowerCase();
          if (limits && !limits.extensions.includes(ext)) {
            throw new Error(
              `不支持的文件类型 .${ext || "?"}，仅支持 ${limits.extensions.join("/")}`
            );
          }
          if (limits && f.size > limits.max_file_size) {
            throw new Error(
              `文件过大（${formatSize(f.size)}），上限 ${formatSize(limits.max_file_size)}`
            );
          }
          const att = await uploadFile(f);
          setAttachments((prev) => [...prev, { ...att, id: uid("att") }]);
        }
      } catch (e) {
        setUploadError((e as Error).message || "上传失败");
      } finally {
        setUploading(false);
      }
    },
    [limits]
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy || uploading) return;

    setInput("");
    // 发送前捕获当前附件并清空，避免发送过程中再次追加导致状态不一致
    const attachmentsToSend = attachments.map((a) => ({
      filename: a.filename,
      content: a.content,
    }));
    setAttachments([]);
    setUploadError(null);
    const botId = uid("bot");

    setMessages((prev) => [
      ...prev,
      { id: uid("user"), role: "user", content: text },
      { id: botId, role: "assistant", content: "", streaming: true, toolCalls: [] },
    ]);
    setBusy(true);

    const controller = new AbortController();
    controllerRef.current = controller;

    let answer = "";
    let thinkingText = "";
    let thinkingStatus: ThinkingStatus = "thinking";
    const toolMap = new Map<string, ToolCall>();
    let usage: Usage | null = null;
    let stopped = false;
    let usedModel = model;
    let usedMode = mode;

    const patch = (p: Partial<Message>) =>
      setMessages((prev) =>
        prev.map((m) => (m.id === botId ? { ...m, ...p } : m))
      );

    try {
      const resp = await apiFetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          model,
          mode,
          attachments: attachmentsToSend,
        }),
        signal: controller.signal,
      });

      if (!resp.ok || !resp.body) {
        const d = (await resp.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new Error(d.detail || "请求失败");
      }

      for await (const ev of readSseStream(resp)) {
        if (ev.error) {
          answer = "";
          patch({ content: ev.error, error: true, streaming: false });
          continue;
        }
        if (ev.usage) {
          usage = ev.usage;
          continue;
        }
        if (ev.model) {
          usedModel = ev.model;
          continue;
        }
        if (ev.mode) {
          usedMode = ev.mode;
          continue;
        }
        if (ev.thinking) {
          thinkingText += ev.thinking;
          patch({ thinking: thinkingText, thinkingStatus: "thinking" });
          continue;
        }
        if (ev.tool_call) {
          const tc = ev.tool_call;
          if (!toolMap.has(tc.id)) {
            toolMap.set(tc.id, { id: tc.id, name: tc.tool, status: "calling" });
            patch({ toolCalls: Array.from(toolMap.values()) });
          }
          continue;
        }
        if (ev.tool_result) {
          const tr = ev.tool_result;
          if (toolMap.has(tr.id)) {
            const existing = toolMap.get(tr.id)!;
            existing.status = "done";
            existing.output = tr.output;
          } else {
            toolMap.set(tr.id, {
              id: tr.id,
              name: tr.tool,
              status: "done",
              output: tr.output,
            });
          }
          patch({ toolCalls: Array.from(toolMap.values()) });
          continue;
        }
        if (ev.delta) {
          if (thinkingStatus !== "done") {
            thinkingStatus = "done";
            patch({ thinkingStatus: "done" });
          }
          answer += ev.delta;
          patch({ content: answer });
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        stopped = true;
      } else {
        patch({ content: (err as Error).message, error: true });
      }
    } finally {
      const modeName = modes.find((m) => m.id === usedMode)?.name ?? "";
      patch({
        streaming: false,
        thinkingStatus: stopped ? "stopped" : "done",
        stopped,
        meta: buildMeta(usedModel, usedMode, usage, stopped, modeName),
      });
      controllerRef.current = null;
      setBusy(false);
      onSettledRef.current?.();
    }
  }, [input, busy, uploading, attachments, sessionId, model, mode, modes]);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  return {
    messages,
    input,
    setInput,
    busy,
    attachments,
    uploading,
    uploadError,
    attachFiles,
    removeAttachment,
    send,
    stop,
  };
}

interface ChatViewProps {
  sessionId: string;
  model: string;
  mode: string;
  modes: ModeOption[];
  hasApiKey: boolean;
  onOpenSettings: () => void;
  onSettled: () => void;
}

export default function ChatView({
  sessionId,
  model,
  mode,
  modes,
  hasApiKey,
  onOpenSettings,
  onSettled,
}: ChatViewProps) {
  const [limits, setLimits] = useState<FileLimits | null>(null);
  const chat = useChat({ sessionId, model, mode, modes, limits, onSettled });
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 拉取上传限制，供上传前本地校验（失败时静默忽略，后端仍会兜底校验）。
  useEffect(() => {
    let cancelled = false;
    fetchFileLimits()
      .then((l) => {
        if (!cancelled) setLimits(l);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.messages]);

  // 输入内容变化时自适应高度；发送后内容清空时，随 state 一起还原为单行高度。
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [chat.input]);

  const accept = (limits?.extensions ?? [
    "txt",
    "md",
    "markdown",
    "csv",
    "pdf",
    "docx",
    "xlsx",
  ])
    .map((e) => "." + e)
    .join(",");

  return (
    <>
      <div id="chat" ref={scrollRef}>
        <div className="container">
          {chat.messages.length === 0 ? (
            <div className="empty">
              <h2>你好，我是 OpenUnknown</h2>
              <div>
                有什么想问的，尽管开始吧。支持天气查询、自定义 MCP 工具，
                也可以上传文档/表格让我读内容作答。
              </div>
            </div>
          ) : (
            chat.messages.map((m) => <MessageRow key={m.id} message={m} />)
          )}
        </div>
      </div>

      {!hasApiKey ? (
        <div className="gate-banner">
          <span>⚠ 尚未配置模型 ApiKey，无法使用对话功能。</span>
          <button className="btn btn-primary" onClick={onOpenSettings}>
            去配置
          </button>
        </div>
      ) : null}

      <footer>
        {chat.attachments.length > 0 || chat.uploading || chat.uploadError ? (
          <div className="attach-row">
            {chat.attachments.map((a) => (
              <span
                key={a.id}
                className="attach-chip"
                title={`${a.file_type} · ${formatSize(a.size)}`}
              >
                <span className="attach-icon">📎</span>
                <span className="attach-name">{a.filename}</span>
                <button
                  className="attach-remove"
                  title="移除"
                  aria-label="移除附件"
                  onClick={() => chat.removeAttachment(a.id)}
                >
                  ×
                </button>
              </span>
            ))}
            {chat.uploading ? <span className="attach-status">解析中…</span> : null}
            {chat.uploadError ? (
              <span className="attach-error">{chat.uploadError}</span>
            ) : null}
          </div>
        ) : null}

        <div className="input-wrap">
          <button
            className="attach-btn"
            title="上传附件（txt / md / csv / pdf / docx / xlsx）"
            aria-label="上传附件"
            disabled={chat.uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            📎
          </button>
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            value={chat.input}
            disabled={!hasApiKey}
            onChange={(e) => chat.setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter" || e.shiftKey) return;
              // 中文/日文等输入法组词确认时的回车（isComposing / keyCode 229）不应触发发送
              if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return;
              e.preventDefault();
              void chat.send();
            }}
          />
          <button
            className={"send" + (chat.busy ? " stop" : "")}
            disabled={!hasApiKey || chat.uploading}
            onClick={() => {
              if (chat.busy) chat.stop();
              else void chat.send();
            }}
          >
            {chat.busy ? "停止" : "发送"}
          </button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={accept}
          style={{ display: "none" }}
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              void chat.attachFiles(e.target.files);
            }
            // 重置 value，允许再次选择同一文件
            e.target.value = "";
          }}
        />

        <div className="hint">回车发送 · Shift + 回车换行 · 支持上传文档/表格作为附件</div>
      </footer>
    </>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // 非安全上下文（如 http）下的降级方案
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* ignore */
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      className={"copy-btn" + (copied ? " copied" : "")}
      title={copied ? "已复制" : "复制"}
      aria-label="复制"
      onClick={() => void copy()}
    >
      {copied ? (
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

function MessageRow({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <div className="avatar">我</div>
        <div className="msg-body">
          <div className="bubble">
            <Markdown content={message.content} autoImageLinks={false} />
          </div>
          <CopyButton text={message.content} />
        </div>
      </div>
    );
  }

  const thinkingHint =
    message.thinkingStatus === "thinking"
      ? "思考中…"
      : message.thinkingStatus === "stopped"
        ? "已停止"
        : "已完成";

  return (
    <>
      {message.thinking ? (
        <details
          className={"thinking" + (message.thinkingStatus === "thinking" ? "" : " done")}
        >
          <summary>
            <span className="thinking-dot" />
            思考过程
            <span className="thinking-hint">{thinkingHint}</span>
          </summary>
          <div className="thinking-body">{message.thinking}</div>
        </details>
      ) : null}

      {message.toolCalls && message.toolCalls.length > 0 ? (
        <div className="tool-trace">
          {message.toolCalls.map((tc) => (
            <span
              key={tc.id}
              className={"tool-badge " + tc.status}
              title={tc.output ?? ""}
            >
              <span className="dot" />
              {tc.name} {tc.status === "calling" ? "调用中..." : "已返回"}
            </span>
          ))}
        </div>
      ) : null}

      <div className="msg bot">
        <div className="avatar">O</div>
        <div className="msg-body">
          <div
            className={
              "bubble" +
              (message.error ? " error" : "") +
              (message.streaming ? " cursor-blink" : "")
            }
          >
            <Markdown content={message.content} />
          </div>
          {message.meta ? (
            <div className={"meta" + (message.stopped ? " stopped" : "")}>
              {message.meta}
            </div>
          ) : null}
          {!message.streaming ? <CopyButton text={message.content} /> : null}
        </div>
      </div>
    </>
  );
}
