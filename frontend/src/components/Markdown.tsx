import { useEffect, useRef, useState } from "react";
import ReactMarkdown, {
  defaultUrlTransform,
  type Components,
} from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

// ---------------------------------------------------------------------------
// 裸图片链接自动识别
// ---------------------------------------------------------------------------

const IMAGE_EXTENSIONS = [
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "bmp",
  "avif",
  "ico",
];

/** 判断一个 http(s) 地址是否「看起来像图片」。 */
function isLikelyImageUrl(url: string): boolean {
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    const path = u.pathname.toLowerCase();
    const ext = path.includes(".") ? path.split(".").pop() || "" : "";
    if (IMAGE_EXTENSIONS.includes(ext)) return true;
    // 无扩展名但查询参数明确标注了图片格式
    const q = u.search.toLowerCase();
    return /(format|fmt|f|type)=(png|jpe?g|gif|webp|avif|svg)/.test(q);
  } catch {
    return false;
  }
}

interface MdastNode {
  type: string;
  children?: MdastNode[];
  url?: string;
  value?: string;
  alt?: string;
  title?: string | null;
  position?: unknown;
}

function walk(node: MdastNode): void {
  if (!node || !Array.isArray(node.children)) return;
  for (let i = 0; i < node.children.length; i += 1) {
    const child = node.children[i];
    const text = child.children?.[0];
    // GFM 已把裸链接转成 <a>，若链接文本就是 URL 本身、且是图片地址，则转成图片节点。
    if (
      child.type === "link" &&
      child.children?.length === 1 &&
      text?.type === "text" &&
      typeof text.value === "string" &&
      text.value === child.url &&
      typeof child.url === "string" &&
      isLikelyImageUrl(child.url)
    ) {
      node.children[i] = {
        type: "image",
        url: child.url,
        alt: "",
        title: null,
        position: child.position,
      };
    }
    walk(node.children[i]);
  }
}

/** remark 插件：把「裸图片 URL」渲染成图片，而非可点击的文字链接。 */
function remarkBareImageLinks() {
  return (tree: MdastNode) => {
    walk(tree);
  };
}

// ---------------------------------------------------------------------------
// Mermaid 渲染
// ---------------------------------------------------------------------------

type Mermaid = typeof import("mermaid").default;

let mermaidPromise: Promise<Mermaid> | null = null;
let mermaidIdCounter = 0;

/** 生成全局唯一的 mermaid 容器 id，避免多次渲染互相冲突。 */
function nextMermaidId(): string {
  mermaidIdCounter += 1;
  return `mmd-${mermaidIdCounter.toString(36)}-${Date.now().toString(36)}`;
}

/** 懒加载 mermaid 并只初始化一次（减小首屏包体，仅在出现图谱时加载）。 */
function loadMermaid(): Promise<Mermaid> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "dark",
        themeVariables: {
          darkMode: true,
          background: "#16181f",
          primaryColor: "#6c8cff",
          primaryTextColor: "#e6e8ee",
          primaryBorderColor: "#8a6cff",
          lineColor: "#9aa0ac",
          secondaryColor: "#1e2129",
          tertiaryColor: "#1e2129",
          clusterBkg: "#1e2129",
          edgeLabelBackground: "#1e2129",
          nodeBorder: "#8a6cff",
          fontSize: "14px",
          fontFamily:
            'ui-sans-serif, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
        },
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

/** 渲染单个 ```mermaid 代码块；流式传输期间做去抖，失败时回退展示源码。 */
function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>("");
  const [failed, setFailed] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [pending, setPending] = useState(false);
  const [preview, setPreview] = useState(false);
  const [scale, setScale] = useState(1);
  const attemptRef = useRef(0);
  const previewSvgRef = useRef<HTMLDivElement>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ active: false, x: 0, y: 0, sl: 0, st: 0 });

  useEffect(() => {
    const trimmed = code.trim();
    const attempt = ++attemptRef.current;
    let cancelled = false;

    if (!trimmed) {
      setSvg("");
      setFailed(false);
      setErrorMsg("");
      setPending(false);
      return;
    }

    setPending(true);
    // 流式期间内容高频变化，稍作去抖再渲染，避免反复解析不完整语法
    const timer = window.setTimeout(async () => {
      try {
        const mermaid = await loadMermaid();
        const id = nextMermaidId();
        const result = await mermaid.render(id, trimmed);
        if (!cancelled && attempt === attemptRef.current) {
          setSvg(result.svg);
          setFailed(false);
          setErrorMsg("");
          setPending(false);
        }
      } catch (err) {
        if (!cancelled && attempt === attemptRef.current) {
          setSvg("");
          setFailed(true);
          setErrorMsg(err instanceof Error ? err.message : String(err));
          setPending(false);
        }
      }
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [code]);

  // 预览打开时：按 Esc 关闭
  useEffect(() => {
    if (!preview) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPreview(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview]);

  // 预览打开时：根据 SVG 原始宽度自适应到容器宽度（viewBox 不受缩放影响）。
  // 下限 100%，保证初始比例不小于原始尺寸，避免大图被缩得太小。
  useEffect(() => {
    if (!preview) return;
    const container = previewScrollRef.current;
    const svgEl = previewSvgRef.current?.querySelector("svg");
    if (!container || !svgEl) return;
    const vbWidth = svgEl.viewBox?.baseVal?.width || 0;
    const natural = vbWidth > 0 ? vbWidth : container.clientWidth;
    const fit = Math.min(3, Math.max(1, (container.clientWidth - 24) / natural));
    setScale(Number.isFinite(fit) ? fit : 1);
  }, [preview, svg]);

  // 预览打开时：触控板捏合 / 鼠标滚轮（含 ctrl/cmd+滚轮）缩放。
  // 使用原生非 passive 监听，确保 preventDefault 生效。
  useEffect(() => {
    if (!preview) return;
    const el = previewScrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      // deltaMode: 0=像素, 1=行, 2=页 —— 统一换算成像素量级
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 120 : 1;
      const delta = e.deltaY * unit;
      if (!delta) return;
      const factor = Math.exp(-delta * 0.0015);
      setScale((s) => Math.min(5, Math.max(0.25, s * factor)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [preview]);

  const zoomIn = () => setScale((s) => Math.min(5, s + 0.2));
  const zoomOut = () => setScale((s) => Math.max(0.25, s - 0.2));
  const zoomReset = () => setScale(1);

  // 放大后可拖拽平移
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    dragRef.current = {
      active: true,
      x: e.clientX,
      y: e.clientY,
      sl: el.scrollLeft,
      st: el.scrollTop,
    };
    try {
      el.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current.active) return;
    const el = e.currentTarget;
    el.scrollLeft = dragRef.current.sl - (e.clientX - dragRef.current.x);
    el.scrollTop = dragRef.current.st - (e.clientY - dragRef.current.y);
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragRef.current.active = false;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  if (svg && !failed) {
    return (
      <>
        <div
          className="mermaid-block mermaid-previewable"
          onClick={() => setPreview(true)}
          title="点击预览大图"
        >
          <span className="mermaid-preview-badge">点击预览</span>
          <div dangerouslySetInnerHTML={{ __html: svg }} />
        </div>

        {preview ? (
          <div className="mermaid-lightbox" onClick={() => setPreview(false)}>
            <div
              className="mermaid-lightbox-body"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mermaid-lightbox-toolbar">
                <button type="button" onClick={zoomOut} title="缩小">
                  −
                </button>
                <span className="mermaid-zoom-label">
                  {Math.round(scale * 100)}%
                </span>
                <button type="button" onClick={zoomIn} title="放大">
                  +
                </button>
                <button type="button" onClick={zoomReset} title="重置为 100%">
                  重置
                </button>
                <button
                  type="button"
                  className="mermaid-lightbox-close"
                  onClick={() => setPreview(false)}
                  title="关闭"
                >
                  ×
                </button>
              </div>
              <div
                className="mermaid-lightbox-scroll"
                ref={previewScrollRef}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
              >
                <div
                  className="mermaid-lightbox-svg"
                  ref={previewSvgRef}
                  style={{ zoom: scale }}
                  dangerouslySetInnerHTML={{ __html: svg }}
                />
              </div>
            </div>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className={"mermaid-block mermaid-fallback" + (pending ? " pending" : "")}>
      {failed ? (
        <>
          <div className="mermaid-hint error">Mermaid 渲染失败，已展示源码</div>
          {errorMsg ? (
            <div className="mermaid-errmsg" title={errorMsg}>
              {errorMsg}
            </div>
          ) : null}
        </>
      ) : (
        <div className="mermaid-hint">{pending ? "正在渲染图谱…" : ""}</div>
      )}
      <pre className="mermaid-code">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown 渲染
// ---------------------------------------------------------------------------

/** 允许普通链接与内联 data:image 图片，拦截 javascript: 等危险协议。 */
function urlTransform(url: string): string {
  const lower = url.trim().toLowerCase();
  if (
    lower.startsWith("javascript:") ||
    lower.startsWith("vbscript:") ||
    lower.startsWith("data:text/html")
  ) {
    return "";
  }
  if (lower.startsWith("data:")) {
    return url;
  }
  return defaultUrlTransform(url);
}

const components: Components = {
  // 去掉 react-markdown 默认的 <pre> 包裹，块级代码由 code 组件自行控制。
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children, ...props }) => {
    const match = /language-([\w-]+)/.exec(className || "");
    const lang = match ? match[1].toLowerCase() : "";
    const raw = String(children);
    const text = raw.replace(/\n$/, "");
    // 有语言标注、或内容含换行时视为块级代码（围栏块），否则视为行内代码。
    const isBlock = Boolean(match) || raw.includes("\n");

    if (lang === "mermaid") {
      return <MermaidBlock code={text} />;
    }

    if (isBlock) {
      return (
        <div className="codeblock">
          {lang ? <div className="codeblock-lang">{lang}</div> : null}
          <pre>
            <code className={className} {...props}>
              {children}
            </code>
          </pre>
        </div>
      );
    }

    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  img: ({ src, alt, ...props }) => (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      className="msg-img"
      onClick={() => {
        // 点击在新标签页打开原图（仅 http(s)，避免 data: 等协议）
        if (typeof src === "string" && /^https?:\/\//i.test(src)) {
          window.open(src, "_blank", "noopener,noreferrer");
        }
      }}
      {...props}
    />
  ),
  a: ({ href, children, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  ),
};

interface MarkdownProps {
  content: string;
  /** 是否把「裸图片 URL」自动渲染成图片（默认开启，用于助手回答；用户输入可关闭）。 */
  autoImageLinks?: boolean;
}

/** 渲染 Markdown（GFM + 换行 + 图片 + Mermaid）。 */
export default function Markdown({ content, autoImageLinks = true }: MarkdownProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[
        remarkGfm,
        remarkBreaks,
        // 用户 query 里的裸图片链接无需渲染成图片，仅在助手回答中自动识别。
        ...(autoImageLinks ? [remarkBareImageLinks] : []),
      ]}
      urlTransform={urlTransform}
      components={components}
    >
      {content}
    </ReactMarkdown>
  );
}
