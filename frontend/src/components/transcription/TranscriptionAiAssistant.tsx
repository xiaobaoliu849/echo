import { useState } from "react";
import {
  Bot,
  Check,
  Copy,
  Download,
  ListTree,
  Loader2,
  Send,
  Sparkles,
} from "lucide-react";
import { createChatCompletion, type ChatMessage } from "../../api";
import { useI18n } from "../../i18n";
import { exportTextFile } from "../../utils/desktopFileSave";

type Props = {
  transcript: string;
  fileName?: string;
  jobId?: string;
};

type AssistantTab = "summary" | "mindmap" | "chat";

const SUMMARY_TEMPLATES = [
  { id: "standard", nameZh: "默认结构化摘要", nameEn: "Standard Summary", prompt: "请为以下音视频转写文稿生成一份结构化专业摘要，包括：1. 核心主题与背景；2. 关键要点提炼（分点叙述）；3. 结论与洞察。" },
  { id: "chapters", nameZh: "时间轴章节与速读", nameEn: "Chapter Breakdown", prompt: "请根据以下转写文稿的主题推进脉络，生成按内容发展的结构化章节速读大纲，并附带核心观点分析。" },
  { id: "meeting", nameZh: "会议纪要与行动待办", nameEn: "Meeting Minutes & Action Items", prompt: "请将以下音视频内容整理为严谨的会议纪要，重点包含：1. 讨论核心议题；2. 关键共识与决策；3. 待办事项与责任分工 (Action Items)。" },
  { id: "keypoints", nameZh: "核心观点与精彩金句", nameEn: "Key Insights & Quotes", prompt: "请从以下文稿中提炼出最有价值的 5-8 条核心观点，并摘录具有代表性的精彩原句金句，进行深度解析。" },
];

export default function TranscriptionAiAssistant({ transcript, fileName }: Props) {
  const { t, language } = useI18n();
  const [activeTab, setActiveTab] = useState<AssistantTab>("summary");

  // Summary State
  const [selectedTemplate, setSelectedTemplate] = useState("standard");
  const [summaryModel, setSummaryModel] = useState("DeepSeek");
  const [summaryLang, setSummaryLang] = useState(language.startsWith("zh") ? "中文" : "English");
  const [summaryResult, setSummaryResult] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryCopied, setSummaryCopied] = useState(false);

  // Mindmap State
  const [mindmapResult, setMindmapResult] = useState("");
  const [mindmapLoading, setMindmapLoading] = useState(false);

  // Video Chat State
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([
    {
      role: "assistant",
      content: t(
        "您好！我是当前视频的 AI 助手。您可以向我提问有关本视频/音频的任何具体内容、数据、观点或细节。",
        "Hello! I am your AI assistant for this video. You can ask me anything about the content, specific topics, data, or arguments."
      ),
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  async function handleGenerateSummary() {
    if (!transcript.trim() || summaryLoading) return;
    setSummaryLoading(true);
    const tmpl = SUMMARY_TEMPLATES.find((item) => item.id === selectedTemplate) || SUMMARY_TEMPLATES[0];

    const systemPrompt = `你是一个顶级的内容提炼专家与音视频分析师。用户提供了音视频转写文稿，请使用${summaryLang}输出高质量、排版优美清晰的 Markdown 格式报告。`;
    const userPrompt = `${tmpl.prompt}\n\n【音视频文件名】: ${fileName || "未命名媒体"}\n\n【转写文稿内容】:\n${transcript.slice(0, 15000)}`;

    try {
      const resp = await createChatCompletion({
        provider: summaryModel,
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: userPrompt },
        ],
        temperature: 0.3,
      });
      setSummaryResult(resp.reply);
    } catch (err: any) {
      setSummaryResult(t(`生成摘要失败: ${err.message || "未知错误"}`, `Failed to generate summary: ${err.message}`));
    } finally {
      setSummaryLoading(false);
    }
  }

  async function handleGenerateMindmap() {
    if (!transcript.trim() || mindmapLoading) return;
    setMindmapLoading(true);

    const systemPrompt = `你是一个结构化思维与思维导图生成专家。请将提供的音视频转写内容总结为层次分明的思维导图树状大纲。使用 Markdown 无序列表格式（# 根节点, ## 分支, - 子节点），层级分明，突出逻辑关系。语言使用${summaryLang}。`;
    const userPrompt = `请为以下音视频内容构建一份全面系统的思维导图大纲：\n\n【媒体文件名】: ${fileName || "未命名"}\n\n【转写文稿】:\n${transcript.slice(0, 15000)}`;

    try {
      const resp = await createChatCompletion({
        provider: summaryModel,
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: userPrompt },
        ],
        temperature: 0.3,
      });
      setMindmapResult(resp.reply);
    } catch (err: any) {
      setMindmapResult(t(`生成思维导图失败: ${err.message}`, `Failed to generate mind map: ${err.message}`));
    } finally {
      setMindmapLoading(false);
    }
  }

  async function handleSendChat() {
    const text = chatInput.trim();
    if (!text || chatLoading) return;
    setChatInput("");
    const newHistory = [...chatMessages, { role: "user" as const, content: text }];
    setChatMessages(newHistory);
    setChatLoading(true);

    const systemPrompt = `你是一个专精于解答当前音视频内容的 AI 问答助手。请根据下方提供的音视频转写全文，精准、客观、有理有据地回答用户的问题。如果文稿中未提及某信息，请如实告知。\n\n【音视频转写全文】:\n${transcript.slice(0, 20000)}`;

    try {
      const apiMessages: ChatMessage[] = [
        { role: "system", content: systemPrompt },
        ...newHistory.map((m) => ({ role: m.role, content: m.content })),
      ];
      const resp = await createChatCompletion({
        provider: summaryModel,
        messages: apiMessages,
        temperature: 0.4,
      });
      setChatMessages([...newHistory, { role: "assistant", content: resp.reply }]);
    } catch (err: any) {
      setChatMessages([
        ...newHistory,
        { role: "assistant", content: t(`回答出错: ${err.message}`, `Error: ${err.message}`) },
      ]);
    } finally {
      setChatLoading(false);
    }
  }

  function copyText(text: string) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setSummaryCopied(true);
      setTimeout(() => setSummaryCopied(false), 2000);
    });
  }

  async function exportMarkdown(title: string, content: string) {
    if (!content) return;
    const base = (fileName || "transcription").replace(/\.[^/.]+$/, "");
    await exportTextFile(`${base}_${title}.md`, content, "text/markdown");
  }

  return (
    <div
      className="vsTranscribeAiAssistant"
      style={{
        display: "flex",
        flexDirection: "column",
        background: "var(--bg-card)",
        border: "1px solid var(--border-color)",
        borderRadius: "14px",
        overflow: "hidden",
        marginTop: "12px",
      }}
    >
      {/* Tab Navigation */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "4px",
          padding: "8px 12px",
          borderBottom: "1px solid var(--border-color)",
          background: "var(--bg-subtle, rgba(0,0,0,0.02))",
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("summary")}
          className={`vsAiTabBtn ${activeTab === "summary" ? "active" : ""}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "6px 14px",
            borderRadius: "8px",
            fontSize: "13px",
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
            background: activeTab === "summary" ? "var(--brand, #6366f1)" : "transparent",
            color: activeTab === "summary" ? "#fff" : "var(--text)",
            transition: "all 0.15s ease",
          }}
        >
          <Sparkles size={15} />
          {t("📋 AI 总结", "📋 AI Summary")}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("mindmap")}
          className={`vsAiTabBtn ${activeTab === "mindmap" ? "active" : ""}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "6px 14px",
            borderRadius: "8px",
            fontSize: "13px",
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
            background: activeTab === "mindmap" ? "var(--brand, #6366f1)" : "transparent",
            color: activeTab === "mindmap" ? "#fff" : "var(--text)",
            transition: "all 0.15s ease",
          }}
        >
          <ListTree size={15} />
          {t("🧠 思维导图", "🧠 Mind Map")}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("chat")}
          className={`vsAiTabBtn ${activeTab === "chat" ? "active" : ""}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "6px 14px",
            borderRadius: "8px",
            fontSize: "13px",
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
            background: activeTab === "chat" ? "var(--brand, #6366f1)" : "transparent",
            color: activeTab === "chat" ? "#fff" : "var(--text)",
            transition: "all 0.15s ease",
          }}
        >
          <Bot size={15} />
          {t("💬 视频问答", "💬 Ask Video")}
        </button>
      </div>

      {/* Content Area */}
      <div style={{ padding: "16px", minHeight: "220px", display: "flex", flexDirection: "column" }}>
        {/* TAB 1: SUMMARY */}
        {activeTab === "summary" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {/* Control Bar */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
              <select
                value={summaryModel}
                onChange={(e) => setSummaryModel(e.target.value)}
                className="vsSelect"
                style={{ height: "34px", fontSize: "13px", borderRadius: "8px", padding: "0 10px" }}
              >
                <option value="DeepSeek">DeepSeek V3 / R1</option>
                <option value="DashScope">Qwen-Max / Qwen-Plus (通义千问)</option>
                <option value="Google">Google Gemini 2.5 Flash</option>
                <option value="OpenRouter">OpenRouter</option>
                <option value="SiliconFlow">SiliconFlow</option>
              </select>

              <select
                value={summaryLang}
                onChange={(e) => setSummaryLang(e.target.value)}
                className="vsSelect"
                style={{ height: "34px", fontSize: "13px", borderRadius: "8px", padding: "0 10px" }}
              >
                <option value="中文">简体中文</option>
                <option value="繁體中文">繁體中文</option>
                <option value="English">English</option>
                <option value="日本語">日本語</option>
                <option value="한국어">한국어</option>
              </select>

              <select
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                className="vsSelect"
                style={{ height: "34px", fontSize: "13px", borderRadius: "8px", padding: "0 10px", flex: 1, minWidth: "160px" }}
              >
                {SUMMARY_TEMPLATES.map((tmpl) => (
                  <option key={tmpl.id} value={tmpl.id}>
                    {language.startsWith("zh") ? tmpl.nameZh : tmpl.nameEn}
                  </option>
                ))}
              </select>

              <button
                type="button"
                onClick={handleGenerateSummary}
                disabled={summaryLoading || !transcript.trim()}
                className="vsBtnPrimary"
                style={{
                  height: "34px",
                  padding: "0 16px",
                  fontSize: "13px",
                  borderRadius: "8px",
                  fontWeight: 600,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                {summaryLoading ? <Loader2 size={14} className="vsSpin" /> : <Sparkles size={14} />}
                {t("AI 总结", "Generate Summary")}
              </button>
            </div>

            {/* Summary Display Box */}
            {summaryResult ? (
              <div
                style={{
                  background: "var(--bg-subtle, rgba(0,0,0,0.02))",
                  border: "1px solid var(--border-color)",
                  borderRadius: "10px",
                  padding: "14px 18px",
                  fontSize: "13px",
                  lineHeight: 1.6,
                  color: "var(--text)",
                  maxHeight: "280px",
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    position: "sticky",
                    top: 0,
                    float: "right",
                    display: "flex",
                    gap: "6px",
                    background: "var(--bg-card)",
                    padding: "4px 8px",
                    borderRadius: "6px",
                    border: "1px solid var(--border-color)",
                    boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
                    zIndex: 2,
                  }}
                >
                  <button
                    type="button"
                    className="vsIconBtn"
                    onClick={() => copyText(summaryResult)}
                    title={t("复制摘要", "Copy Summary")}
                    style={{ width: "26px", height: "26px" }}
                  >
                    {summaryCopied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
                  </button>
                  <button
                    type="button"
                    className="vsIconBtn"
                    onClick={() => exportMarkdown("AI总结", summaryResult)}
                    title={t("导出 Markdown", "Export Markdown")}
                    style={{ width: "26px", height: "26px" }}
                  >
                    <Download size={14} />
                  </button>
                </div>
                {summaryResult}
              </div>
            ) : (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "36px 20px",
                  color: "var(--muted)",
                  fontSize: "13px",
                  textAlign: "center",
                  border: "1px dashed var(--border-color)",
                  borderRadius: "10px",
                }}
              >
                <Sparkles size={24} style={{ marginBottom: "8px", opacity: 0.6 }} />
                <span>{t("点击上方「AI 总结」按钮，一键提炼音视频核心内容要点", "Click 'Generate Summary' to extract key takeaways from this media")}</span>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: MIND MAP */}
        {activeTab === "mindmap" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "13px", color: "var(--muted)" }}>
                {t("将音视频文稿提炼为逻辑层级清晰的思维导图大纲", "Extract a clear hierarchical mind map outline from the transcript")}
              </span>
              <button
                type="button"
                onClick={handleGenerateMindmap}
                disabled={mindmapLoading || !transcript.trim()}
                className="vsBtnPrimary"
                style={{
                  height: "34px",
                  padding: "0 16px",
                  fontSize: "13px",
                  borderRadius: "8px",
                  fontWeight: 600,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                {mindmapLoading ? <Loader2 size={14} className="vsSpin" /> : <ListTree size={14} />}
                {t("生成思维导图", "Generate Mind Map")}
              </button>
            </div>

            {mindmapResult ? (
              <div
                style={{
                  background: "var(--bg-subtle, rgba(0,0,0,0.02))",
                  border: "1px solid var(--border-color)",
                  borderRadius: "10px",
                  padding: "14px 18px",
                  fontSize: "13px",
                  lineHeight: 1.6,
                  color: "var(--text)",
                  maxHeight: "280px",
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                }}
              >
                {mindmapResult}
              </div>
            ) : (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "36px 20px",
                  color: "var(--muted)",
                  fontSize: "13px",
                  textAlign: "center",
                  border: "1px dashed var(--border-color)",
                  borderRadius: "10px",
                }}
              >
                <ListTree size={24} style={{ marginBottom: "8px", opacity: 0.6 }} />
                <span>{t("点击按钮生成结构化知识导图大纲", "Click button to generate a structured mind map")}</span>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: VIDEO CHAT */}
        {activeTab === "chat" && (
          <div style={{ display: "flex", flexDirection: "column", height: "280px" }}>
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
                paddingRight: "6px",
                marginBottom: "12px",
              }}
            >
              {chatMessages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "85%",
                    padding: "8px 14px",
                    borderRadius: "12px",
                    fontSize: "13px",
                    lineHeight: 1.5,
                    background: msg.role === "user" ? "var(--brand, #6366f1)" : "var(--bg-subtle, rgba(0,0,0,0.04))",
                    color: msg.role === "user" ? "#fff" : "var(--text)",
                  }}
                >
                  {msg.content}
                </div>
              ))}
              {chatLoading && (
                <div
                  style={{
                    alignSelf: "flex-start",
                    padding: "8px 14px",
                    borderRadius: "12px",
                    fontSize: "13px",
                    background: "var(--bg-subtle, rgba(0,0,0,0.04))",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                >
                  <Loader2 size={14} className="vsSpin" />
                  <span>{t("AI 正在阅读文稿并思考…", "AI is reading and thinking…")}</span>
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSendChat();
                  }
                }}
                placeholder={t("向 AI 追问有关此视频的任何细节… (按 Enter 发送)", "Ask anything about this video... (Press Enter)")}
                className="vsInput"
                style={{ flex: 1, height: "38px", borderRadius: "10px", fontSize: "13px", padding: "0 12px" }}
              />
              <button
                type="button"
                onClick={handleSendChat}
                disabled={chatLoading || !chatInput.trim()}
                className="vsBtnPrimary"
                style={{ height: "38px", width: "42px", borderRadius: "10px", padding: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
              >
                <Send size={15} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
