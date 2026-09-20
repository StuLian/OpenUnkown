import McpModal from "../components/McpModal";
import MemoryModal from "../components/MemoryModal";
import SettingsModal from "../components/SettingsModal";
import UsageModal from "../components/UsageModal";
import type { McpServer, SettingsInfo } from "../types";

interface ModalsProps {
  mcpOpen: boolean;
  settingsOpen: boolean;
  memoryOpen: boolean;
  usageOpen: boolean;
  mcpServers: McpServer[];
  settings: SettingsInfo | null;
  onCloseMcp: () => void;
  onCloseSettings: () => void;
  onCloseMemory: () => void;
  onCloseUsage: () => void;
  onMcpChanged: () => void;
  onSettingsChanged: () => void;
  onMemoryChanged: (n: number) => void;
  onUsageChanged: (n: number) => void;
}

/**
 * 应用级弹窗的集中渲染（MCP / 模型设置 / 我的记忆 / 用量统计）。
 *
 * 从 `App/index.tsx` 拆出，使其回落到 300 行内（`coding.md` §3）。
 * 纯展示编排：open 状态与数据都由 App 持有，这里只负责渲染与转发回调。
 */
export default function Modals({
  mcpOpen,
  settingsOpen,
  memoryOpen,
  usageOpen,
  mcpServers,
  settings,
  onCloseMcp,
  onCloseSettings,
  onCloseMemory,
  onCloseUsage,
  onMcpChanged,
  onSettingsChanged,
  onMemoryChanged,
  onUsageChanged,
}: ModalsProps) {
  return (
    <>
      <McpModal
        open={mcpOpen}
        onClose={onCloseMcp}
        servers={mcpServers}
        onChanged={onMcpChanged}
      />
      <SettingsModal
        open={settingsOpen}
        onClose={onCloseSettings}
        settings={settings}
        onChanged={onSettingsChanged}
      />
      <MemoryModal
        open={memoryOpen}
        onClose={onCloseMemory}
        onChanged={onMemoryChanged}
      />
      <UsageModal
        open={usageOpen}
        onClose={onCloseUsage}
        onChanged={onUsageChanged}
      />
    </>
  );
}
