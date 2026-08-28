// 统一的请求封装：携带 JWT、处理 401 登出事件、JSON 解析与错误抛出。

import { LS_TOKEN } from "../lib/storage";

// 401 时抛出此事件，由 AuthContext 监听并清空会话状态。
export const UNAUTHORIZED_EVENT = "openunknown:unauthorized";

let authToken = localStorage.getItem(LS_TOKEN) ?? "";

export function getToken(): string {
  return authToken;
}

export function setToken(token: string | null): void {
  authToken = token ?? "";
  if (authToken) {
    localStorage.setItem(LS_TOKEN, authToken);
  } else {
    localStorage.removeItem(LS_TOKEN);
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);

  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 401) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    throw new ApiError(401, "登录已过期，请重新登录");
  }
  return resp;
}

/** 请求并解析 JSON；非 2xx 时抛出携带 detail 的 ApiError。 */
export async function apiJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const resp = await apiFetch(url, options);
  const data = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
  if (!resp.ok) {
    const detail = data.detail;
    throw new ApiError(
      resp.status,
      typeof detail === "string" ? detail : "请求失败"
    );
  }
  return data as T;
}
