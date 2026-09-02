import { memo, useCallback, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useI18n } from "../../i18n";

function extractText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    const props = (node as { props: { children?: ReactNode } }).props;
    return extractText(props?.children);
  }
  return "";
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // fall through
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.inset = "-9999px auto auto -9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

const CodeBlock = memo(function CodeBlock({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const text = extractText(children);
    if (!text) return;
    void copyToClipboard(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }, [children]);

  return (
    <div className="vsMdPreWrap">
      <button
        type="button"
        className={`vsMdCopyBtn${copied ? " copied" : ""}`}
        onClick={handleCopy}
        aria-label={copied ? t("已复制", "Copied") : t("复制代码", "Copy code")}
        title={copied ? t("已复制", "Copied") : t("复制代码", "Copy code")}
      >
        {copied ? "✓" : "⧉"}
      </button>
      <pre>{children}</pre>
    </div>
  );
});

const markdownComponents: Components = {
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>;
  },
  a({ href, children, node: _node, ...rest }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
        {children}
      </a>
    );
  },
};

type MarkdownContentProps = {
  content: string;
  isStreaming?: boolean;
};

function MarkdownContentImpl({ content, isStreaming }: MarkdownContentProps) {
  return (
    <div className="vsMarkdownContent">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
      {isStreaming ? <span className="vsStreamingCursor" aria-hidden="true" /> : null}
    </div>
  );
}

const MarkdownContent = memo(MarkdownContentImpl);

export default MarkdownContent;
