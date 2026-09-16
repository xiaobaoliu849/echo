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
        <div className="vsCanvasToolbar">
          <div className="vsCanvasControlsWrap">
            <div className="vsCanvasSegmentedControl" role="group" aria-label={t("组件语言模式", "Component Mode")}>
              <button
                type="button"
                className={`vsCanvasSegmentedBtn ${canvas.mode === "react" ? "active" : ""}`}
                onClick={() => canvas.setMode("react")}
                title={t("React 模式 (JSX / 组件渲染)", "React Mode (JSX / Component)")}
              >
                React
              </button>
              <button
                type="button"
                className={`vsCanvasSegmentedBtn ${canvas.mode === "html" ? "active" : ""}`}
                onClick={() => canvas.setMode("html")}
                title={t("HTML 模式 (HTML / CSS / JS 页面渲染)", "HTML Mode (HTML / CSS / JS)")}
              >
                HTML
              </button>
            </div>

            <div className="vsCanvasDivider" />

            <div className="vsCanvasSegmentedControl" role="group" aria-label={t("视图切换", "View Switch")}>
              <button
                type="button"
                className={`vsCanvasSegmentedBtn ${canvas.activeView === "preview" ? "active brandGlow" : ""}`}
                onClick={() => canvas.setActiveView("preview")}
                title={t("预览视图 (查看交互渲染效果)", "Preview View (Interactive Render)")}
              >
                <Monitor size={14} />
                <span>{t("预览", "Preview")}</span>
              </button>
              <button
                type="button"
                className={`vsCanvasSegmentedBtn ${canvas.activeView === "code" ? "active brandGlow" : ""}`}
                onClick={() => canvas.setActiveView("code")}
                title={t("代码视图 (查看和复制源代码)", "Code View (Inspect and Copy Code)")}
              >
                <Code2 size={14} />
                <span>{t("代码", "Code")}</span>
              </button>
            </div>
          </div>

          <div className="vsCanvasControlsWrap">
            <button
              type="button"
              onClick={canvas.undo}
              disabled={canvas.codeHistory.length <= 1}
              className="vsCanvasSegmentedBtn"
              style={{
                border: "1px solid var(--border-color)",
                opacity: canvas.codeHistory.length <= 1 ? 0.45 : 1,
                cursor: canvas.codeHistory.length <= 1 ? "not-allowed" : "pointer",
              }}
              title={t("撤销上一步更改", "Undo change")}
            >
              <Undo2 size={13} />
              <span>{t("撤销", "Undo")}</span>
            </button>
            <button
              type="button"
              onClick={canvas.clearCanvas}
              className="vsCanvasSegmentedBtn"
              style={{ border: "1px solid var(--border-color)" }}
              title={t("清空画布内容", "Clear Canvas")}
            >
              <Trash2 size={13} />
              <span>{t("清空", "Clear")}</span>
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
