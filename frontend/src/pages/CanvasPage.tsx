import { useRef, useEffect } from "react";
import { useI18n } from "../i18n";
import useCanvas from "../hooks/useCanvas";
import CanvasPreview from "../components/canvas/CanvasPreview";
import CanvasCodeView from "../components/canvas/CanvasCodeView";
import CanvasPromptBar from "../components/canvas/CanvasPromptBar";
import { Loader2, Monitor, Code2, Trash2, Undo2 } from "lucide-react";

interface CanvasPageProps {
  errorRuntimeContext?: any;
}

export default function CanvasPage({ errorRuntimeContext: _ }: CanvasPageProps) {
  const { t, language } = useI18n();
  const canvas = useCanvas({ language });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [canvas.messages, canvas.isGenerating]);

  const hasCode = canvas.currentCode.trim().length > 0;

  return (
    <div className="vsCanvasWorkspace" style={{ display: "flex", width: "100%", height: "100%", overflow: "hidden", flexDirection: "row" }}>
      
      {/* Left Panel: Chat & Prompt */}
      <div className="vsCanvasPromptPanel" style={{ width: "40%", minWidth: "300px", display: "flex", flexDirection: "column", borderRight: "1px solid var(--border-color)", background: "var(--bg-primary)" }}>
        <div className="vsCanvasMessageList custom-scrollbar" style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "16px" }}>
          {canvas.messages.length === 0 ? (
            <div className="vsCanvasEmptyState" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)", gap: "12px" }}>
              <Monitor size={48} opacity={0.2} />
              <p>{t("描述你想生成的 UI，或者粘贴截图", "Describe the UI you want to build, or paste a screenshot")}</p>
            </div>
          ) : (
            canvas.messages.map((msg, idx) => (
              <div key={msg.id || idx} className={`vsCanvasMessage ${msg.role}`} style={{ display: "flex", flexDirection: "column", alignSelf: msg.role === "user" ? "flex-end" : "flex-start", maxWidth: "85%" }}>
                <div style={{ padding: "10px 14px", borderRadius: "12px", background: msg.role === "user" ? "var(--user-bg)" : "var(--assistant-bg)", color: msg.role === "user" ? "white" : "var(--text-primary)", wordBreak: "break-word" }}>
                  {msg.images && msg.images.length > 0 && (
                    <div style={{ display: "flex", gap: "4px", marginBottom: "8px", flexWrap: "wrap" }}>
                      {msg.images.map((img, i) => <img key={i} src={img} style={{ width: "100px", borderRadius: "4px" }} alt="attachment" />)}
                    </div>
                  )}
                  {msg.content}
                </div>
              </div>
            ))
          )}
          {canvas.isGenerating && (
            <div className="vsCanvasThinking" style={{ display: "flex", gap: "8px", alignItems: "center", color: "var(--text-secondary)", padding: "12px" }}>
              <Loader2 size={16} className="spin" />
              <span>{t("正在生成...", "Generating...")}</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        
        {canvas.error && (
          <div style={{ padding: "8px 16px", color: "red", background: "rgba(255,0,0,0.1)", fontSize: "12px" }}>
            {canvas.error}
          </div>
        )}

        <CanvasPromptBar
          onSubmit={(prompt, images) => {
            if (hasCode) {
              canvas.reviseCode(prompt);
            } else {
              canvas.generateFromPrompt(prompt, images);
            }
          }}
          isGenerating={canvas.isGenerating}
          placeholder={t("描述你的界面...", "Describe your UI...")}
        />
      </div>

      {/* Right Panel: Output */}
      <div className="vsCanvasOutputPanel" style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--surface)", minWidth: 0 }}>
        
        {/* Toolbar */}
        <div className="vsCanvasToolbar" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid var(--border-color)", background: "var(--bg-card)" }}>
          <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
            <div className="vsCanvasModeToggle" style={{ display: "flex", background: "var(--bg-primary)", borderRadius: "8px", padding: "2px", border: "1px solid var(--border-color)" }}>
              <button onClick={() => canvas.setMode("react")} style={{ padding: "4px 12px", border: "none", borderRadius: "6px", background: canvas.mode === "react" ? "var(--surface-strong)" : "transparent", cursor: "pointer", fontWeight: canvas.mode === "react" ? 600 : 400, color: "var(--text-primary)" }}>React</button>
              <button onClick={() => canvas.setMode("html")} style={{ padding: "4px 12px", border: "none", borderRadius: "6px", background: canvas.mode === "html" ? "var(--surface-strong)" : "transparent", cursor: "pointer", fontWeight: canvas.mode === "html" ? 600 : 400, color: "var(--text-primary)" }}>HTML</button>
            </div>
            
            <div className="vsCanvasViewToggle" style={{ display: "flex", gap: "8px" }}>
              <button onClick={() => canvas.setActiveView("preview")} style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 12px", border: "none", background: canvas.activeView === "preview" ? "var(--brand-soft)" : "transparent", color: canvas.activeView === "preview" ? "var(--brand-dark)" : "var(--text-secondary)", borderRadius: "6px", cursor: "pointer" }}>
                <Monitor size={16} /> {t("预览", "Preview")}
              </button>
              <button onClick={() => canvas.setActiveView("code")} style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 12px", border: "none", background: canvas.activeView === "code" ? "var(--brand-soft)" : "transparent", color: canvas.activeView === "code" ? "var(--brand-dark)" : "var(--text-secondary)", borderRadius: "6px", cursor: "pointer" }}>
                <Code2 size={16} /> {t("代码", "Code")}
              </button>
            </div>
          </div>
          
          <div style={{ display: "flex", gap: "8px" }}>
            <button onClick={canvas.undo} disabled={canvas.codeHistory.length <= 1} style={{ padding: "6px 10px", border: "1px solid var(--border-color)", background: "var(--bg-primary)", borderRadius: "6px", cursor: canvas.codeHistory.length <= 1 ? "not-allowed" : "pointer", opacity: canvas.codeHistory.length <= 1 ? 0.5 : 1, display: "flex", alignItems: "center", gap: "6px", color: "var(--text-primary)" }}>
              <Undo2 size={14} /> {t("撤销", "Undo")}
            </button>
            <button onClick={canvas.clearCanvas} style={{ padding: "6px 10px", border: "1px solid var(--border-color)", background: "var(--bg-primary)", borderRadius: "6px", cursor: "pointer", display: "flex", alignItems: "center", gap: "6px", color: "var(--text-primary)" }}>
              <Trash2 size={14} /> {t("清空", "Clear")}
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
          {!hasCode ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
              {t("暂无代码", "No code yet")}
            </div>
          ) : canvas.activeView === "preview" ? (
            <CanvasPreview code={canvas.currentCode} mode={canvas.mode} />
          ) : (
            <CanvasCodeView code={canvas.currentCode} onCopy={() => {}} />
          )}
        </div>
      </div>
      
      {/* Inline styles for responsive layout */}
      <style>{`
        @media (max-width: 768px) {
          .vsCanvasWorkspace {
            flex-direction: column !important;
          }
          .vsCanvasPromptPanel {
            width: 100% !important;
            height: 50%;
            border-right: none !important;
            border-bottom: 1px solid var(--border-color);
          }
          .vsCanvasOutputPanel {
            height: 50%;
          }
        }
      `}</style>
    </div>
  );
}
