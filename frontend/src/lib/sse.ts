import type { Usage } from "../types";

// 后端 /api/chat 以 SSE 形式逐条推送的事件负载。
export interface StreamEvent {
  error?: string;
  model?: string;
  mode?: string;
  notice?: string;
  thinking?: string;
  delta?: string;
  tool_call?: { id: string; tool: string; args?: unknown };
  tool_result?: { id: string; tool: string; output?: string };
  usage?: Usage;
}

/**
 * 逐行解析 SSE 响应体，产出解析后的 JSON 事件。
 * 遇到 `[DONE]` 或空行会跳过，断流后自然结束。
 */
export async function* readSseStream(
  resp: Response
): AsyncGenerator<StreamEvent> {
  const reader = resp.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      try {
        yield JSON.parse(data) as StreamEvent;
      } catch {
        // 忽略无法解析的行。
      }
    }
  }
}
