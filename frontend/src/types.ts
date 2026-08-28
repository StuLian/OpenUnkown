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

export interface Challenge {
  nonce: string;
  public_key_pem: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}
