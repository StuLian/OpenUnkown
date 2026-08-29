import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
} from "react";
import { apiFetch } from "../api/client";
import {
  attachUrl,
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
  images?: string[];
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

// 剪贴板/拖拽的 MIME → 扩展名（图片 + 文档），用于合成上传文件名
function extFromMime(mime: string): string | null {
  const m = mime.toLowerCase();
  if (m.includes("png")) return "png";
  if (m.includes("webp")) return "webp";
  if (m.includes("gif")) return "gif";
  if (m.includes("jpeg") || m.includes("jpg")) return "jpg";
  if (m.includes("pdf")) return "pdf";
  if (m.includes("csv")) return "csv";
  if (m.includes("spreadsheetml") || m.includes("excel")) return "xlsx";
  if (m.includes("wordprocessingml") || m.includes("word")) return "docx";
  if (m.includes("markdown")) return "md";
  if (m.includes("text/plain")) return "txt";
  return null;
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
              images: m.images,
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
          const isImage = limits?.image_extensions.includes(ext) ?? false;
          const allowedExts = limits
            ? [...limits.extensions, ...limits.image_extensions]
            : [];
          const maxSize = limits
            ? isImage
              ? limits.max_image_size
              : limits.max_file_size
            : Infinity;
          if (limits && !allowedExts.includes(ext)) {
            throw new Error(
              `不支持的文件类型 .${ext || "?"}，仅支持 ${allowedExts.join("/")}`
            );
          }
          if (f.size > maxSize) {
            throw new Error(
              `文件过大（${formatSize(f.size)}），上限 ${formatSize(maxSize)}`
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

  // 粘贴链接：下载并解析，结果挂到附件列表。
  const attachUrlRequest = useCallback(async (url: string) => {
    setUploading(true);
    setUploadError(null);
    try {
      const att = await attachUrl(url);
      setAttachments((prev) => [...prev, { ...att, id: uid("att") }]);
    } catch (e) {
      setUploadError((e as Error).message || "链接解析失败");
    } finally {
      setUploading(false);
    }
  }, []);

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
      file_type: a.file_type,
      content: a.file_type === "image" ? a.ocr_text ?? "" : a.content ?? "",
      image: a.file_type === "image" ? a.image ?? null : null,
    }));
    const imageUrls = attachments
      .filter((a) => a.file_type === "image" && a.image)
      .map((a) => a.image as string);
    setAttachments([]);
    setUploadError(null);
    const botId = uid("bot");

    setMessages((prev) => [
      ...prev,
      { id: uid("user"), role: "user", content: text, images: imageUrls },
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
    let notice: string | null = null;

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
        if (ev.notice) {
          notice = ev.notice;
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
      const metaBase = buildMeta(usedModel, usedMode, usage, stopped, modeName);
      patch({
        streaming: false,
        thinkingStatus: stopped ? "stopped" : "done",
        stopped,
        meta: notice
          ? metaBase
            ? `⚠ ${notice} · ${metaBase}`
            : `⚠ ${notice}`
          : metaBase,
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
    setUploadError,
    attachFiles,
    attachUrl: attachUrlRequest,
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

  const accept = [
    ...(limits?.extensions ?? ["txt", "md", "markdown", "csv", "pdf", "docx", "xlsx"]),
    ...(limits?.image_extensions ?? ["jpg", "jpeg", "png", "webp", "gif"]),
  ]
    .map((e) => "." + e)
    .join(",");

  // 粘贴：剪贴板里的图片/文件直接上传；整段纯链接自动下载上传。
  function handlePaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const items = e.clipboardData?.items;
    if (items) {
      const files: File[] = [];
      for (const item of Array.from(items)) {
        if (item.kind !== "file") continue;
        const blob = item.getAsFile();
        if (!blob) continue;
        const ext = extFromMime(item.type) || extFromMime(blob.type);
        const name = blob.name || `pasted.${ext || "bin"}`;
        files.push(new File([blob], name, { type: blob.type || item.type }));
      }
      if (files.length > 0) {
        e.preventDefault();
        void chat.attachFiles(files);
        return;
      }
    }
    const text = e.clipboardData?.getData("text") ?? "";
    const trimmed = text.trim();
    if (/^https?:\/\/\S+$/i.test(trimmed)) {
      e.preventDefault();
      void chat.attachUrl(trimmed);
      return;
    }
    // 从系统文件管理器复制的文件往往只拿到 file:// 路径，浏览器无法读取其内容
    if (/^file:\/\//i.test(trimmed)) {
      e.preventDefault();
      chat.setUploadError(
        "浏览器无法读取本地文件路径，请直接把文件拖拽到输入框，或点击 📎 按钮选择"
      );
    }
  }

  return (
    <>
      <div id="chat" ref={scrollRef}>
        <div className="container">
          {chat.messages.length === 0 ? (
            <div className="empty">
              <h2>你好，我是 OpenUnknown</h2>
              <div>
                有什么想问的，尽管开始吧。支持天气查询、自定义 MCP 工具，
                也可以上传文档/表格/图片让我读内容作答。
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

      <footer
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            void chat.attachFiles(e.dataTransfer.files);
          }
        }}
      >
        {chat.attachments.length > 0 || chat.uploading || chat.uploadError ? (
          <div className="attach-row">
            {chat.attachments.map((a) => {
              const isImage = a.file_type === "image" && !!a.image;
              const title = isImage
                ? `${a.filename} · ${a.width ?? "?"}×${a.height ?? "?"} · ${formatSize(a.size)} · 发送后提取文字并看图`
                : `${a.file_type} · ${formatSize(a.size)}`;
              return (
                <span key={a.id} className="attach-chip" title={title}>
                  {isImage ? (
                    <img className="attach-thumb" src={a.image} alt="" />
                  ) : (
                    <span className="attach-icon">📎</span>
                  )}
                  <span className="attach-name">{a.filename}</span>
                  {isImage ? <span className="attach-ocr">看图+文字</span> : null}
                  <button
                    className="attach-remove"
                    title="移除"
                    aria-label="移除附件"
                    onClick={() => chat.removeAttachment(a.id)}
                  >
                    ×
                  </button>
                </span>
              );
            })}
            {chat.uploading ? <span className="attach-status">解析中…</span> : null}
            {chat.uploadError ? (
              <span className="attach-error">{chat.uploadError}</span>
            ) : null}
          </div>
        ) : null}

        <div className="input-wrap">
          <button
            className="attach-btn"
            title="上传附件（文档/表格/图片）"
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
            onPaste={handlePaste}
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

        <div className="hint">回车发送 · Shift + 回车换行 · 支持上传/拖拽/粘贴图片与文档</div>
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
          {message.images && message.images.length > 0 ? (
            <div className="msg-imgs">
              {message.images.map((src, i) => (
                <img
                  key={i}
                  src={src}
                  alt=""
                  className="msg-img-attach"
                  loading="lazy"
                />
              ))}
            </div>
          ) : null}
          {message.content ? (
            <div className="bubble">
              <Markdown content={message.content} autoImageLinks={false} />
            </div>
          ) : null}
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
