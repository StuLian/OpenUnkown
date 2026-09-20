// 与后端 API 返回结构一一对应的类型定义。

export interface User {
  user_id: string;
  username: string;
  has_api_key: boolean;
}

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  images?: string[];
  attachments?: string[];
  usage?: Usage;
}

export interface ModelOption {
  id: string;
  name: string;
}

export interface ModeOption {
  id: string;
  name: string;
  description?: string;
  enable_thinking?: boolean;
}

export interface PlatformOption {
  id: string;
  name: string;
}

export type McpServerType = "stdio" | "sse";

export interface McpServer {
  id: string;
  name: string;
  server_type: McpServerType;
  command: string | null;
  args: string[];
  env: Record<string, string>;
  url: string | null;
  enabled: boolean;
  created_at?: number;
  updated_at?: number;
}

export interface McpTool {
  name: string;
  description?: string;
}

export interface SettingsInfo {
  platforms: PlatformOption[];
  default_platform: string;
  current: {
    platform: string;
    has_key: boolean;
    key_masked: string;
  };
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface UsageTotals extends Usage {
  requests: number;
}

export interface UsageByModel extends UsageTotals {
  model: string;
}

export interface UsageByDay extends UsageTotals {
  date: string;
}

export interface UsageStats {
  totals: UsageTotals;
  by_model: UsageByModel[];
  by_day: UsageByDay[];
}

export interface Challenge {
  nonce: string;
  public_key_pem: string;
}

export interface FileLimits {
  extensions: string[];
  image_extensions: string[];
  max_file_size: number;
  max_image_size: number;
  max_content_chars: number;
}

export interface Attachment {
  id: string;
  filename: string;
  file_type: string; // 文档类型（txt/markdown/csv/pdf/docx/xlsx）或 "image"
  size: number;
  // 文本附件
  content?: string;
  char_count?: number;
  truncated?: boolean;
  // 图片附件
  image?: string; // data URL
  mime?: string;
  width?: number;
  height?: number;
  ocr_text?: string | null;
  ocr_error?: string | null;
}

export interface AuthResponse {
  token: string;
  user: User;
}

// ===== trace（runs）与反馈 =====

export interface RunSummary {
  id: string;
  session_id: string;
  model: string;
  mode: string;
  input_text: string;
  final_answer_preview: string;
  latency_ms: number;
  error: string | null;
  flags: string[];
  feedback_count: number;
  created_at: number;
}

export interface TraceToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface TraceMessage {
  type: string;
  /** 逻辑标记：如 "memory"（记忆注入段），前端优先用它作为 tag 展示。 */
  kind?: string;
  content: string | unknown;
  name?: string;
  tool_calls?: TraceToolCall[];
  tool_call_id?: string;
}

export interface ToolOutputRecord {
  id: string;
  name: string;
  output: string;
}

export interface RetrievedDoc {
  name: string;
  address: string;
  desc: string;
  score: number;
}

export interface FeedbackRecord {
  id: string;
  run_id: string;
  user_id: string;
  rating: number;
  tags: string[];
  comment: string;
  created_at: number;
}

export interface RunDetail {
  id: string;
  session_id: string;
  model: string;
  mode: string;
  platform: string;
  prompt_version: string;
  input_text: string;
  messages: TraceMessage[];
  tool_calls: TraceToolCall[];
  tool_outputs: ToolOutputRecord[];
  retrieved_docs: RetrievedDoc[];
  final_answer: string;
  usage: Usage;
  latency_ms: number;
  error: string | null;
  flags: string[];
  created_at: number;
  feedback: FeedbackRecord[];
}

export interface RunsPage {
  runs: RunSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** 长期记忆（事实）：系统在对话中自动记住的关于用户的稳定信息。 */
export interface MemoryFact {
  id: string;
  content: string;
  created_at: number;
}
