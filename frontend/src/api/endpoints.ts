// 后端各业务域的 API 封装，全部返回类型化数据。

import { apiJson } from "./client";
import type {
  AuthResponse,
  Challenge,
  HistoryMessage,
  McpServer,
  McpServerType,
  McpTool,
  ModelOption,
  ModeOption,
  Session,
  SettingsInfo,
  User,
  UsageStats,
} from "../types";

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

// ===== 认证 =====
export function fetchMe(): Promise<User> {
  return apiJson<User>("/api/auth/me");
}

export function fetchChallenge(): Promise<Challenge> {
  return apiJson<Challenge>("/api/auth/challenge");
}

export function loginRequest(
  username: string,
  password_ciphertext: string,
  nonce: string
): Promise<AuthResponse> {
  return apiJson<AuthResponse>(
    "/api/auth/login",
    jsonInit("POST", { username, password_ciphertext, nonce })
  );
}

export function registerRequest(
  username: string,
  password_ciphertext: string,
  nonce: string
): Promise<AuthResponse> {
  return apiJson<AuthResponse>(
    "/api/auth/register",
    jsonInit("POST", { username, password_ciphertext, nonce })
  );
}

export function logoutRequest(): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
}

// ===== 模型 / 模式 =====
export function fetchModels(): Promise<{ models: ModelOption[]; default: string }> {
  return apiJson<{ models: ModelOption[]; default: string }>("/api/models");
}

export function fetchModes(): Promise<{ modes: ModeOption[]; default: string }> {
  return apiJson<{ modes: ModeOption[]; default: string }>("/api/modes");
}

// ===== 会话 =====
export function fetchSessions(): Promise<{ sessions: Session[] }> {
  return apiJson<{ sessions: Session[] }>("/api/sessions");
}

export function fetchSessionMessages(
  sessionId: string
): Promise<{ messages: HistoryMessage[] }> {
  return apiJson<{ messages: HistoryMessage[] }>(
    `/api/sessions/${encodeURIComponent(sessionId)}/messages`
  );
}

export function deleteSessionRequest(
  sessionId: string
): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" }
  );
}

// ===== MCP 扩展 =====
export interface McpServerPayload {
  id?: string;
  name: string;
  server_type: McpServerType;
  command: string | null;
  args: string[];
  env: Record<string, string>;
  url: string | null;
  enabled: boolean;
}

export function fetchMcpServers(): Promise<{ servers: McpServer[] }> {
  return apiJson<{ servers: McpServer[] }>("/api/mcp/servers");
}

export function saveMcpServer(
  payload: McpServerPayload
): Promise<{ server: McpServer }> {
  return apiJson<{ server: McpServer }>(
    "/api/mcp/servers",
    jsonInit("POST", payload)
  );
}

export function deleteMcpServerRequest(serverId: string): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>(
    `/api/mcp/servers/${encodeURIComponent(serverId)}`,
    { method: "DELETE" }
  );
}

export function toggleMcpServerRequest(
  serverId: string,
  enabled: boolean
): Promise<{ server: McpServer }> {
  return apiJson<{ server: McpServer }>(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/toggle`,
    jsonInit("PATCH", { enabled })
  );
}

export function testMcpRequest(
  payload: McpServerPayload
): Promise<{ ok: boolean; tools: McpTool[]; error?: string }> {
  return apiJson<{ ok: boolean; tools: McpTool[]; error?: string }>(
    "/api/mcp/test",
    jsonInit("POST", payload)
  );
}

export function importMcpRequest(
  config: unknown
): Promise<{ ok: boolean; imported_count: number; servers: McpServer[] }> {
  return apiJson<{ ok: boolean; imported_count: number; servers: McpServer[] }>(
    "/api/mcp/import",
    jsonInit("POST", { config })
  );
}

// ===== 模型服务设置 =====
export function fetchSettings(): Promise<SettingsInfo> {
  return apiJson<SettingsInfo>("/api/settings");
}

export function testApiKeyRequest(
  api_key: string,
  platform: string
): Promise<{ ok: boolean; error?: string }> {
  return apiJson<{ ok: boolean; error?: string }>(
    "/api/settings/test",
    jsonInit("POST", { api_key, platform })
  );
}

export function saveApiKeyRequest(
  api_key: string,
  platform: string
): Promise<{ ok: boolean; platform: string; key_masked: string }> {
  return apiJson<{ ok: boolean; platform: string; key_masked: string }>(
    "/api/settings/api-key",
    jsonInit("PUT", { api_key, platform })
  );
}

export function clearApiKeyRequest(
  platform: string
): Promise<{ ok: boolean }> {
  return apiJson<{ ok: boolean }>(
    `/api/settings/api-key?platform=${encodeURIComponent(platform)}`,
    { method: "DELETE" }
  );
}

export function fetchUsage(): Promise<UsageStats> {
  return apiJson<UsageStats>("/api/usage");
}
