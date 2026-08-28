import { useEffect, useState } from "react";
import {
  clearApiKeyRequest,
  saveApiKeyRequest,
  testApiKeyRequest,
} from "../api/endpoints";
import type { SettingsInfo } from "../types";
import Modal from "./Modal";

type Result = { kind: "" | "success" | "error"; text: string } | null;

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  settings: SettingsInfo | null;
  onChanged: () => void;
}

export default function SettingsModal({
  open,
  onClose,
  settings,
  onChanged,
}: SettingsModalProps) {
  const [platform, setPlatform] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && settings) {
      setPlatform(settings.default_platform);
      setApiKey("");
      setShowKey(false);
      setResult(null);
    }
  }, [open, settings]);

  const hasKey = settings?.current.has_key ?? false;

  async function handleTest() {
    const key = apiKey.trim();
    if (!key) {
      setResult({ kind: "error", text: "请输入 ApiKey 后再测试" });
      return;
    }
    setTesting(true);
    setResult({ kind: "", text: "正在测试连接..." });
    try {
      const res = await testApiKeyRequest(key, platform);
      setResult(
        res.ok
          ? { kind: "success", text: "连接成功，ApiKey 可用" }
          : { kind: "error", text: "连接失败: " + (res.error || "未知错误") }
      );
    } catch (err) {
      setResult({ kind: "error", text: "测试失败: " + (err as Error).message });
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    const key = apiKey.trim();
    if (!key) {
      setResult({ kind: "error", text: "请输入 ApiKey" });
      return;
    }
    setSaving(true);
    try {
      const res = await saveApiKeyRequest(key, platform);
      if (res.ok) {
        setResult({ kind: "success", text: "已加密保存并生效" });
        onChanged();
        setTimeout(onClose, 600);
      } else {
        setResult({ kind: "error", text: "保存失败" });
      }
    } catch (err) {
      setResult({ kind: "error", text: "保存失败: " + (err as Error).message });
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    if (!confirm("确定清除已保存的 ApiKey 吗？清除后将无法使用对话功能。")) {
      return;
    }
    try {
      await clearApiKeyRequest(platform);
      setApiKey("");
      setResult({ kind: "success", text: "已清除 ApiKey" });
      onChanged();
    } catch (err) {
      setResult({ kind: "error", text: "清除失败: " + (err as Error).message });
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      small
      title="模型服务设置"
      subtitle="配置大模型 ApiKey，保存后立即生效"
    >
      <div className="settings-form">
        <div className="form-row">
          <label>模型平台</label>
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            {(settings?.platforms ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="form-row">
          <label>ApiKey</label>
          <div className="key-input-wrap">
            <input
              type={showKey ? "text" : "password"}
              placeholder="sk-..."
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              type="button"
              className="btn-icon"
              onClick={() => setShowKey((v) => !v)}
            >
              {showKey ? "隐藏" : "显示"}
            </button>
          </div>
          <div className="field-hint">
            {hasKey
              ? "当前已配置 · " + (settings?.current.key_masked ?? "")
              : "尚未配置 ApiKey，请填写并保存"}
          </div>
        </div>

        <div className="form-actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={testing}
            onClick={() => void handleTest()}
          >
            测试连接
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={saving}
            onClick={() => void handleSave()}
          >
            保存
          </button>
        </div>

        {hasKey ? (
          <div className="settings-reset">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void handleClear()}
            >
              清除 ApiKey
            </button>
          </div>
        ) : null}

        {result ? (
          <div
            className={
              "test-result-box" + (result.kind ? " " + result.kind : "")
            }
          >
            {result.text}
          </div>
        ) : null}

        <div className="settings-note">
          ApiKey 仅加密存储在本地数据库（用你的登录密码派生密钥加密），明文不回显。
          未配置 ApiKey 时无法使用对话功能，请务必填写真实可用的 Key。
        </div>
      </div>
    </Modal>
  );
}
