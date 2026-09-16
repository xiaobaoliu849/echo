import { useI18n } from "../../i18n";
import { Copy } from "lucide-react";
import { useState } from "react";

interface CanvasCodeViewProps {
  code: string;
  onCopy: () => void;
}

export default function CanvasCodeView({ code, onCopy }: CanvasCodeViewProps) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      onCopy();
    });
  };

  return (
    <div className="vsCanvasCodeView" style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <div className="vsCanvasCodeHeader" style={{ display: "flex", justifyContent: "flex-end", padding: "8px", background: "var(--bg-secondary)", borderBottom: "1px solid var(--border-color)" }}>
        <button className="vsCanvasCopyBtn" onClick={handleCopy} style={{ display: "flex", alignItems: "center", gap: "6px", background: "transparent", border: "1px solid var(--border-color)", borderRadius: "6px", padding: "4px 8px", cursor: "pointer", fontSize: "12px", color: "var(--text-primary)" }}>
          <Copy size={14} />
          {copied ? t("已复制", "Copied") : t("复制", "Copy")}
        </button>
      </div>
      <pre className="vsCanvasCodeBlock custom-scrollbar" style={{ margin: 0, padding: "16px", overflow: "auto", flex: 1, background: "var(--bg-primary)", color: "var(--text-primary)", fontFamily: "monospace", fontSize: "13px", lineHeight: 1.5 }}>
        <code>{code}</code>
      </pre>
    </div>
  );
}
