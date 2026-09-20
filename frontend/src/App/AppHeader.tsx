import type { ModeOption, ModelOption } from "../types";

interface AppHeaderProps {
  isTraces: boolean;
  modes: ModeOption[];
  models: ModelOption[];
  currentMode: string;
  currentModel: string;
  onChangeMode: (id: string) => void;
  onChangeModel: (id: string) => void;
  onBack: () => void;
}

/**
 * 顶栏：对话页显示「标题 + 模式/模型选择器」，Trace 轨迹页显示「返回对话」。
 *
 * 从 `App/index.tsx` 拆出，使其回落到 300 行内（`coding.md` §3）。
 * 纯展示组件：状态与持久化仍由 App 持有，这里只回调。
 */
export default function AppHeader({
  isTraces,
  modes,
  models,
  currentMode,
  currentModel,
  onChangeMode,
  onChangeModel,
  onBack,
}: AppHeaderProps) {
  return (
    <header>
      <div>
        <h1>{isTraces ? "Trace 轨迹" : "OpenUnknown"}</h1>
        <div className="sub">
          {isTraces
            ? "每次对话的完整运行轨迹 · 原始报文 / 工具调用 / 检索"
            : "基于 LangGraph · 支持 MCP 扩展"}
        </div>
      </div>

      {!isTraces ? (
        <>
          <div className="mode-picker">
            <label htmlFor="modeSelect">模式</label>
            <select
              id="modeSelect"
              value={currentMode}
              onChange={(e) => onChangeMode(e.target.value)}
            >
              {modes.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
          <div className="model-picker">
            <label htmlFor="modelSelect">模型</label>
            <select
              id="modelSelect"
              value={currentModel}
              onChange={(e) => onChangeModel(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        </>
      ) : null}

      {isTraces ? (
        <button className="btn btn-secondary trace-toggle" onClick={onBack}>
          返回对话
        </button>
      ) : null}
    </header>
  );
}
