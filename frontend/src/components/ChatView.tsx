import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import { fetchSessionMessages } from "../api/endpoints";
import { readSseStream } from "../lib/sse";
import type { ModeOption, Usage } from "../types";

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
  onSettled?: () => void;
}

function useChat({ sessionId, model, mode, modes, onSettled }: UseChatOptions) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
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
          data.messages.map((m) => ({
            id: uid("hist"),
            role: m.role,
            content: m.content,
          }))
        );
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    setInput("");
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
  }, [input, busy, sessionId, model, mode, modes]);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  return { messages, input, setInput, busy, send, stop };
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
  const chat = useChat({ sessionId, model, mode, modes, onSettled });
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.messages]);

  function autoGrow() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }

  return (
    <>
      <div id="chat" ref={scrollRef}>
        <div className="container">
          {chat.messages.length === 0 ? (
            <div className="empty">
              <h2>你好，我是 OpenUnknown</h2>
              <div>
                有什么想问的，尽管开始吧。支持天气查询与自定义 MCP 工具。
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
        <div className="input-wrap">
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            value={chat.input}
            disabled={!hasApiKey}
            onChange={(e) => {
              chat.setInput(e.target.value);
              autoGrow();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void chat.send();
              }
            }}
          />
          <button
            className={"send" + (chat.busy ? " stop" : "")}
            disabled={!hasApiKey}
            onClick={() => {
              if (chat.busy) chat.stop();
              else void chat.send();
            }}
          >
            {chat.busy ? "停止" : "发送"}
          </button>
        </div>
        <div className="hint">回车发送 · Shift + 回车换行</div>
      </footer>
    </>
  );
}

function MessageRow({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <div className="avatar">我</div>
        <div className="bubble">{message.content}</div>
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
        <div
          className={
            "bubble" +
            (message.error ? " error" : "") +
            (message.streaming ? " cursor-blink" : "")
          }
        >
          {message.content}
        </div>
        {message.meta ? (
          <div className={"meta" + (message.stopped ? " stopped" : "")}>
            {message.meta}
          </div>
        ) : null}
      </div>
    </>
  );
}
