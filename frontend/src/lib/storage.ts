// localStorage 键名与工具函数。

export const LS_TOKEN = "openunknown:token";
export const LS_SESSION = "openunknown:current_session";
export const LS_MODEL = "openunknown:model";
export const LS_MODE = "openunknown:mode";

export function newSessionId(): string {
  return (
    "sess-" +
    (crypto.randomUUID
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36))
  );
}
