import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSpeakAudio, translateText, type ChatMessage, type TtsEngine } from "../api";
import ErrorNotice from "../components/ErrorNotice";
import ChatInputBar from "../components/chat/ChatInputBar";
import MarkdownContent from "../components/chat/MarkdownContent";
import { isVoiceRealtimeModel, type UseChatResult } from "../hooks/useChat";
import type { UseVoiceChatResult } from "../hooks/useVoiceChat";
import type { UseSettingsResult } from "../hooks/useSettings";
import CanvasPreview from "../components/canvas/CanvasPreview";
import CanvasCodeView from "../components/canvas/CanvasCodeView";
import { PanelRight, Code2, Monitor, X, Trash2 } from "lucide-react";
import { useI18n } from "../i18n";
import type { ErrorRuntimeContext } from "../types/ui";

type Props = {
  chat: UseChatResult;
  voiceChat: UseVoiceChatResult;
  settings?: UseSettingsResult;
  errorRuntimeContext: ErrorRuntimeContext;
  onOpenSettings?: () => void;
  onOpenPal?: () => void;
};

type WordLookupState = {
  word: string;
  definition?: string;
  loading: boolean;
  error?: string;
  x: number;
  y: number;
};

/* ── Inline SVG icons ── */
const CopyIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="8" y="8" rx="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>
);
const TranslateIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 8 6 6"></path><path d="m4 14 6-6 2-3"></path><path d="M2 5h12"></path><path d="M7 2h1"></path><path d="m22 22-5-10-5 10"></path><path d="M14 18h6"></path></svg>
);
const SpeakerIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>
);
const StopTtsIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect></svg>
);
const TrashIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
);
const RefreshIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M16 3h5v5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 21H3v-5"></path></svg>
);
const ChevronDownIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"></path></svg>
);

function mapProviderToEngine(provider?: string): TtsEngine {
  if (!provider) return "edge";
  const p = provider.toLowerCase();
  if (p.includes("edge")) return "edge";
  if (p.includes("qwen")) return "qwen_flash";
  if (p.includes("minimax")) return "minimax";
  if (p.includes("xiaomi")) return "xiaomi";
  if (p.includes("openai")) return "openai";
  if (p.includes("elevenlabs")) return "elevenlabs";
  if (p.includes("chattts")) return "chattts";
  if (p.includes("gpt_sovits")) return "gpt_sovits";
  if (p.includes("doubao")) return "doubao";
  return "edge";
}

function cleanMarkdownForTts(text: string): string {
  if (!text) return "";
  let clean = text;
  clean = clean.replace(/```[\s\S]*?```/g, "");
  clean = clean.replace(/`([^`]+)`/g, "$1");
  clean = clean.replace(/\*\*([^*]+)\*\*/g, "$1");
  clean = clean.replace(/\*([^*]+)\*/g, "$1");
  clean = clean.replace(/__([^_]+)__/g, "$1");
  clean = clean.replace(/_([^_]+)_/g, "$1");
  clean = clean.replace(/^#+\s+/gm, "");
  clean = clean.replace(/<[^>]*>/g, "");
  clean = clean.trim();
  return clean;
}

function getDomainFromUrl(urlStr: string): string {
  try {
    const u = new URL(urlStr);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return urlStr || "";
  }
}

async function copyTextToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall through
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.inset = "-9999px auto auto -9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) {
    throw new Error("clipboard copy failed");
  }
}

type TranslateFn = (zh: string, en: string) => string;

type MessageBubbleProps = {
  msg: ChatMessage;
  messageKey: string;
  index: number;
  chatBusy: boolean;
  isStreamingPlaceholder: boolean;
  isThinkingActive: boolean;
  copied: boolean;
  playing: boolean;
  loadingTts: boolean;
  sourcesOpen: boolean;
  reasoningCollapsed: boolean;
  translation?: string;
  translating?: boolean;
  t: TranslateFn;
  onCopy: (content: string, key: string) => void;
  onPlayTts: (content: string, key: string) => void;
  onTranslate?: (content: string, key: string) => void;
  onRegenerate: (index: number) => void;
  onDelete: (index: number) => void;
  onToggleSources: (key: string) => void;
  onToggleReasoning: (key: string) => void;
  onOpenInCanvas?: (code: string, mode: "react" | "html", title?: string) => void;
};

const TOOL_RESULT_STATUSES = new Set(["result", "completed", "context_injected", "result_delivered"]);

function MessageBubbleImpl({
  msg,
  messageKey,
  index,
  chatBusy,
  isStreamingPlaceholder,
  isThinkingActive,
  copied,
  playing,
  loadingTts,
  sourcesOpen,
  reasoningCollapsed,
  translation,
  translating,
  t,
  onCopy,
  onPlayTts,
  onTranslate,
  onRegenerate,
  onDelete,
  onToggleSources,
  onToggleReasoning,
  onOpenInCanvas,
}: MessageBubbleProps) {
  const toolCalls = msg.toolCalls;
  const lastTool =
    toolCalls && toolCalls.length > 0
      ? ([...toolCalls].reverse().find((r) => TOOL_RESULT_STATUSES.has(r.status)) ?? toolCalls[toolCalls.length - 1])
      : null;
  const sourcesList = lastTool?.sources || [];
  const reasoningText = msg.reasoningContent;

  const hasMeta =
    msg.memorySaved || msg.memoriesUsed || msg.memorySourceSummary || msg.interrupted || (toolCalls && toolCalls.length > 0);

  let toolLabel = "";
  const toolMeta: string[] = [];
  if (lastTool) {
    toolLabel =
      lastTool.tool_name === "search_web"
        ? t("🔍 联网搜索", "🔍 Web Search")
        : lastTool.tool_name === "recall_memory"
        ? t("🧠 记忆检索", "🧠 Memory Recall")
        : lastTool.tool_name === "translate_text"
        ? t("🌐 翻译", "🌐 Translate")
        : lastTool.tool_name === "summarize_transcript"
        ? t("📝 摘要", "📝 Summary")
        : `🔧 ${lastTool.tool_name || t("工具", "Tool")}`;
    if (lastTool.source_count != null && lastTool.source_count > 0) toolMeta.push(t(`${lastTool.source_count} 来源`, `${lastTool.source_count} sources`));
    if (lastTool.elapsed_ms != null) toolMeta.push(`${(lastTool.elapsed_ms / 1000).toFixed(1)}s`);
  }
  const isSourcesClickable = sourcesList.length > 0;

  const codeBlockMatch = useMemo(() => {
    if (msg.role !== "assistant" || !msg.content) return null;
    const match = msg.content.match(/```(?:jsx|tsx|react|javascript|js)?\s*\n([\s\S]*?)```/i);
    if (match && match[1]?.trim()) {
      return { code: match[1].trim(), mode: "react" as const };
    }
    const htmlMatch = msg.content.match(/```(?:html|xml)?\s*\n([\s\S]*?)```/i);
    if (htmlMatch && htmlMatch[1]?.trim()) {
      return { code: htmlMatch[1].trim(), mode: "html" as const };
    }
    return null;
  }, [msg.role, msg.content]);

  return (
    <div className={msg.role === "user" ? "bubble user hasCopyAction" : "bubble assistant hasCopyAction"}>
      {hasMeta ? (
        <div className="vsBubbleMeta">
          {msg.memorySaved ? <span className="vsBubbleMemoryTag saved">{t("✓ 已记忆", "✓ Saved")}</span> : null}
          {msg.memoriesUsed ? (
            <span className="vsBubbleMemoryTag used">
              {t(`🧠 回忆了 ${msg.memoriesUsed} 条`, `🧠 Recalled ${msg.memoriesUsed}`)}
            </span>
          ) : null}
          {msg.memorySourceSummary ? <span className="vsBubbleMemoryTag used">{msg.memorySourceSummary}</span> : null}
          {msg.interrupted ? <span className="vsBubbleMemoryTag used">{t("已打断", "Interrupted")}</span> : null}
          {lastTool ? (
            <span
              className={`vsBubbleMemoryTag tool${isSourcesClickable ? " clickable" : ""}${sourcesOpen ? " active" : ""}`}
              title={lastTool.query || ""}
              onClick={isSourcesClickable ? () => onToggleSources(messageKey) : undefined}
            >
              {[toolLabel, ...toolMeta].join(" · ")}
            </span>
          ) : null}
        </div>
      ) : null}

      {reasoningText && (
        <div className="vsDeepThinkingSection">
          <button
            type="button"
            className="vsDeepThinkingToggle"
            onClick={() => onToggleReasoning(messageKey)}
          >
            <span className="vsBrainIcon">🧠</span>
            <span className="vsDeepThinkingTitle">{t("深度思考", "Deep thinking")}</span>
            <span className={`vsThinkingArrow ${reasoningCollapsed ? "collapsed" : ""}`}>▾</span>
          </button>
          {!reasoningCollapsed && (
            <div className="vsDeepThinkingContent">{reasoningText}</div>
          )}
        </div>
      )}

      {lastTool && sourcesOpen && sourcesList.length > 0 ? (
        <div className="vsSearchSourcesCard">
          {lastTool.query ? (
            <div className="vsSearchQueryText">
              🔍 {t("搜索关键词", "Search Query")}: "{lastTool.query}"
            </div>
          ) : null}
          <div className="vsSearchSourcesList">
            {sourcesList.map((src: { title?: string; uri?: string; url?: string; snippet?: string }, sIdx: number) => {
              const domain = getDomainFromUrl(src.uri || src.url || "");
              return (
                <div key={sIdx} className="vsSearchSourceItem">
                  <div className="vsSearchSourceHeader">
                    <span className="vsSearchSourceDomain">{domain || "Web"}</span>
                    <a
                      href={src.uri || src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="vsSearchSourceLink"
                      title={src.uri || src.url}
                    >
                      {src.title || src.uri || src.url} ↗
                    </a>
                  </div>
                  {src.snippet && <div className="vsSearchSourceSnippet">{src.snippet}</div>}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {msg.attachments && msg.attachments.length > 0 && (
        <div className="vsMessageAttachments">
          {msg.attachments.map((att, attIdx) => {
            const isImage = att.type === "image" || att.dataUrl?.startsWith("data:image/") || /\.(png|jpe?g|webp|gif)$/i.test(att.name);
            const imgSrc = att.dataUrl || att.url;
            return isImage && imgSrc ? (
              <div key={`${attIdx}-${att.name}`} className="vsMessageImageWrapper">
                <img src={imgSrc} alt={att.name} className="vsMessageImage" />
                <span className="vsMessageImageCaption">{att.name}</span>
              </div>
            ) : (
              <div key={`${attIdx}-${att.name}`} className="vsMessageFilePill">
                <span className="vsMessageFileIcon">{att.type === "pdf" ? "📕" : "📄"}</span>
                <span className="vsMessageFileName">{att.name}</span>
              </div>
            );
          })}
        </div>
      )}

      {msg.role === "assistant" && isThinkingActive ? (
        <div className="vsThinkingDots" aria-label={t("正在思考", "Thinking")}>
          <span /><span /><span />
        </div>
      ) : msg.role === "assistant" ? (
        <MarkdownContent content={msg.content} isStreaming={isStreamingPlaceholder && msg.content.length > 0} />
      ) : (
        <p>{msg.content}</p>
      )}

      {translation && (
        <div className="vsBubbleTranslation">
          <div className="vsBubbleTransHeader">
            <span>🌐</span>
            <span>{t("译文", "Translation")}</span>
          </div>
          <p>{translation}</p>
        </div>
      )}

      <div className="vsBubbleActions">
        <button
          type="button"
          className={`vsBubbleActionBtn${copied ? " copied" : ""}`}
          aria-label={copied ? t("已复制", "Copied") : t("复制消息", "Copy message")}
          title={copied ? t("已复制", "Copied") : t("复制消息", "Copy message")}
          onClick={() => onCopy(msg.content, messageKey)}
        >
          <CopyIcon />
        </button>

        {msg.role === "assistant" && onTranslate && (
          <button
            type="button"
            className={`vsBubbleActionBtn${translation ? " active" : ""}`}
            aria-label={translating ? t("正在翻译...", "Translating...") : translation ? t("已翻译", "Translated") : t("翻译回答", "Translate reply")}
            title={translating ? t("正在翻译...", "Translating...") : translation ? t("已翻译", "Translated") : t("翻译回答", "Translate reply")}
            onClick={() => onTranslate(msg.content, messageKey)}
            disabled={translating}
          >
            {translating ? <span className="spinner-mini" /> : <TranslateIcon />}
          </button>
        )}

        {msg.role === "assistant" && (
          <button
            type="button"
            className={`vsBubbleActionBtn${playing ? " playing" : ""}`}
            aria-label={playing ? t("停止朗读", "Stop speech") : t("朗读回答", "Read aloud")}
            title={playing ? t("停止朗读", "Stop speech") : t("朗读回答", "Read aloud")}
            onClick={() => onPlayTts(msg.content, messageKey)}
            disabled={loadingTts}
          >
            {loadingTts ? (
              <span className="spinner-mini" />
            ) : playing ? (
              <StopTtsIcon />
            ) : (
              <SpeakerIcon />
            )}
          </button>
        )}

        {msg.role === "assistant" && codeBlockMatch && onOpenInCanvas && (
          <button
            type="button"
            className="vsBubbleActionBtn"
            aria-label={t("在画布中预览", "Preview on Canvas")}
            title={t("在画布中预览", "Preview on Canvas")}
            onClick={() => onOpenInCanvas(codeBlockMatch.code, codeBlockMatch.mode)}
          >
            <PanelRight size={14} />
          </button>
        )}

        {msg.role === "assistant" && (
          <button
            type="button"
            className="vsBubbleActionBtn"
            aria-label={t("重新生成", "Regenerate")}
            title={t("重新生成", "Regenerate")}
            onClick={() => onRegenerate(index)}
            disabled={chatBusy}
          >
            <RefreshIcon />
          </button>
        )}

        <button
          type="button"
          className="vsBubbleActionBtn danger"
          aria-label={t("删除消息", "Delete message")}
          title={t("删除消息", "Delete message")}
          onClick={() => onDelete(index)}
        >
          <TrashIcon />
        </button>
      </div>
    </div>
  );
}

const MessageBubble = memo(MessageBubbleImpl);

export default function ChatPage({
  chat,
  voiceChat,
  settings,
  errorRuntimeContext,
  onOpenSettings,
  onOpenPal,
}: Props) {
  const { t } = useI18n();

  const [copiedMessageKey, setCopiedMessageKey] = useState<string>("");
  const [playingMessageKey, setPlayingMessageKey] = useState<string>("");
  const [loadingTtsMessageKey, setLoadingTtsMessageKey] = useState<string>("");
  const [ttsPlaybackError, setTtsPlaybackError] = useState<string>("");
  const [expandedSourcesKey, setExpandedSourcesKey] = useState<string | null>(null);
  const [collapsedReasoningKeys, setCollapsedReasoningKeys] = useState<Record<string, boolean>>({});
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [translatingKeys, setTranslatingKeys] = useState<Record<string, boolean>>({});
  const [wordLookup, setWordLookup] = useState<WordLookupState | null>(null);

  // ── Visual Canvas Side Panel State ──
  const [showCanvas, setShowCanvas] = useState(false);
  const [canvasMode, setCanvasMode] = useState<"react" | "html">("react");
  const [canvasView, setCanvasView] = useState<"preview" | "code">("preview");
  const [canvasCode, setCanvasCode] = useState("");
  const [canvasTitle, setCanvasTitle] = useState("");

  // Sync with realtime voice canvas artifact (e.g. Gemini 3.8 Live render_canvas tool)
  useEffect(() => {
    if (voiceChat.voiceChatCanvas?.code) {
      setCanvasCode(voiceChat.voiceChatCanvas.code);
      setCanvasMode(voiceChat.voiceChatCanvas.mode || "react");
      setCanvasTitle(voiceChat.voiceChatCanvas.title || "Live Component");
      setShowCanvas(true);
    }
  }, [voiceChat.voiceChatCanvas]);

  const handleOpenInCanvas = useCallback((code: string, mode: "react" | "html" = "react", title: string = "Preview Component") => {
    setCanvasCode(code);
    setCanvasMode(mode);
    setCanvasTitle(title);
    setShowCanvas(true);
  }, []);

  const bodyRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lookupPopoverRef = useRef<HTMLDivElement>(null);
  const [showScrollBottomBtn, setShowScrollBottomBtn] = useState(false);
  const isProgrammaticScrollRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioObjectUrlRef = useRef<string | null>(null);
  const copyResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Close word lookup on outside click or Escape
  useEffect(() => {
    if (!wordLookup) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (lookupPopoverRef.current && !lookupPopoverRef.current.contains(e.target as Node)) {
        setWordLookup(null);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setWordLookup(null);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [wordLookup]);

  const isVoiceActive = voiceChat.voiceChatRecording || voiceChat.voiceChatConnected;

  const combinedMessages = useMemo(() => {
    return [...chat.chatMessages, ...(voiceChat.sessionSummary || [])];
  }, [chat.chatMessages, voiceChat.sessionSummary]);

  const showWelcome = combinedMessages.length === 0 && !isVoiceActive;

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      if (audioObjectUrlRef.current) {
        URL.revokeObjectURL(audioObjectUrlRef.current);
        audioObjectUrlRef.current = null;
      }
    };
  }, []);

  async function playTts(content: string, key: string) {
    if (playingMessageKey === key) {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingMessageKey("");
      return;
    }

    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioObjectUrlRef.current) {
      URL.revokeObjectURL(audioObjectUrlRef.current);
      audioObjectUrlRef.current = null;
    }

    const cleanText = cleanMarkdownForTts(content);
    if (!cleanText) return;

    setLoadingTtsMessageKey(key);
    setTtsPlaybackError("");

    try {
      const ttsObj = (settings?.settingsData?.tts_settings as Record<string, unknown> | undefined) || {};
      const selectedTtsProvider = typeof ttsObj.provider === "string" ? ttsObj.provider : "edge";
      const configuredVoice = typeof ttsObj.default_voice === "string" ? ttsObj.default_voice : "zh-CN-XiaoxiaoNeural";
      const selectedEngine = mapProviderToEngine(selectedTtsProvider);

      let voice = configuredVoice;
      if (selectedEngine === "edge") {
        const hasJapanese = /[\u3040-\u309f\u30a0-\u30ff]/.test(cleanText);
        const hasKorean = /[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]/.test(cleanText);
        const hasRussian = /[\u0400-\u04ff]/.test(cleanText);
        const hasChinese = /[\u4e00-\u9fff]/.test(cleanText);
        const hasEnglish = /[a-zA-Z]/.test(cleanText);

        const voiceLower = (configuredVoice || "").toLowerCase();

        if (hasJapanese) {
          if (!voiceLower.includes("ja")) {
            voice = "ja-JP-NanamiNeural";
          }
        } else if (hasKorean) {
          if (!voiceLower.includes("ko")) {
            voice = "ko-KR-SunHiNeural";
          }
        } else if (hasRussian) {
          if (!voiceLower.includes("ru")) {
            voice = "ru-RU-SvetlanaNeural";
          }
        } else if (hasChinese) {
          if (!voiceLower.includes("zh")) {
            voice = "zh-CN-XiaoxiaoNeural";
          }
        } else if (hasEnglish) {
          if (!voiceLower.includes("en")) {
            voice = "en-US-AvaNeural";
          }
        }
      }

      const res = await fetchSpeakAudio({
        text: cleanText,
        voice,
        engine: selectedEngine,
      });

      const url = URL.createObjectURL(res.blob);
      audioObjectUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;

      audio.onended = () => {
        setPlayingMessageKey("");
        audioRef.current = null;
        if (audioObjectUrlRef.current) {
          URL.revokeObjectURL(audioObjectUrlRef.current);
          audioObjectUrlRef.current = null;
        }
      };

      audio.onerror = () => {
        setPlayingMessageKey("");
        setLoadingTtsMessageKey("");
        setTtsPlaybackError(t("语音播放出错，请重试。", "Audio playback error. Please try again."));
        audioRef.current = null;
      };

      await audio.play();
      setPlayingMessageKey(key);
    } catch (err) {
      setTtsPlaybackError(
        t(
          `合成语音失败: ${err instanceof Error ? err.message : String(err)}`,
          `TTS error: ${err instanceof Error ? err.message : String(err)}`
        )
      );
    } finally {
      setLoadingTtsMessageKey("");
    }
  }

  const scrollToBottom = useCallback((smooth = true) => {
    const el = bodyRef.current;
    if (!el) return;
    isProgrammaticScrollRef.current = true;
    if (typeof el.scrollTo === "function") {
      el.scrollTo({
        top: el.scrollHeight,
        behavior: smooth ? "smooth" : "auto",
      });
    } else {
      el.scrollTop = el.scrollHeight;
    }
    shouldStickToBottomRef.current = true;
    setShowScrollBottomBtn(false);
  }, []);

  useEffect(() => {
    if (shouldStickToBottomRef.current) {
      scrollToBottom(false);
    }
  }, [combinedMessages, voiceChat.voiceChatTranscript, voiceChat.voiceChatReply, scrollToBottom]);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;

    const performAutoScroll = () => {
      if (shouldStickToBottomRef.current && bodyRef.current) {
        isProgrammaticScrollRef.current = true;
        bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
        setShowScrollBottomBtn(false);
      }
    };

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => {
        performAutoScroll();
      });
      resizeObserver.observe(el);
      const messageList = el.querySelector(".vsMessageList");
      if (messageList) {
        resizeObserver.observe(messageList);
      }
    }

    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
    };
  }, []);

  useEffect(() => () => {
    if (copyResetTimerRef.current !== null) {
      clearTimeout(copyResetTimerRef.current);
    }
  }, []);

  async function copyMessage(content: string, key: string) {
    const cleanContent = content.trim();
    if (!cleanContent) return;
    try {
      await copyTextToClipboard(cleanContent);
      setCopiedMessageKey(key);
      if (copyResetTimerRef.current !== null) {
        clearTimeout(copyResetTimerRef.current);
      }
      copyResetTimerRef.current = setTimeout(() => {
        copyResetTimerRef.current = null;
        setCopiedMessageKey("");
      }, 1600);
    } catch {
      setCopiedMessageKey("");
    }
  }

  const playTtsRef = useRef(playTts);
  playTtsRef.current = playTts;
  const stablePlayTts = useCallback((content: string, key: string) => {
    void playTtsRef.current(content, key);
  }, []);
  const copyMessageRef = useRef(copyMessage);
  copyMessageRef.current = copyMessage;
  const stableCopyMessage = useCallback((content: string, key: string) => {
    void copyMessageRef.current(content, key);
  }, []);
  const chatRef = useRef(chat);
  chatRef.current = chat;
  const stableDeleteMessage = useCallback((index: number) => {
    chatRef.current.onDeleteMessage?.(index);
  }, []);
  const stableRegenerateMessage = useCallback((index: number) => {
    void chatRef.current.onRegenerateMessage?.(index);
  }, []);
  const stableToggleSources = useCallback((key: string) => {
    setExpandedSourcesKey((prev) => (prev === key ? null : key));
  }, []);
  const stableToggleReasoning = useCallback((key: string) => {
    setCollapsedReasoningKeys((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);
  const handleLookupWordText = useCallback(async (cleanWord: string, x: number, y: number) => {
    if (!cleanWord || cleanWord.length <= 1) return;
    setWordLookup({
      word: cleanWord,
      loading: true,
      x,
      y,
    });

    try {
      const res = await translateText({
        text: cleanWord,
        source_language: "auto",
        target_language: "zh",
      });
      setWordLookup((prev) =>
        prev && prev.word === cleanWord
          ? { ...prev, definition: res.translated_text, loading: false }
          : prev
      );
    } catch {
      setWordLookup((prev) =>
        prev && prev.word === cleanWord
          ? { ...prev, error: t("查词失败", "Lookup failed"), loading: false }
          : prev
      );
    }
  }, [t]);

  const handleWordClick = useCallback(async (e: React.MouseEvent, rawWord: string) => {
    e.stopPropagation();
    const cleanWord = rawWord.replace(/^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$/g, "").trim();
    if (!cleanWord || cleanWord.length <= 1) return;

    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    void handleLookupWordText(cleanWord, rect.left + rect.width / 2, rect.top);
  }, [handleLookupWordText]);

  const handleMessageListMouseUp = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;
    const rawSelected = selection.toString().trim();
    const cleanWord = rawSelected.replace(/^[^\w\u4e00-\u9fa5]+|[^\w\u4e00-\u9fa5]+$/g, "").trim();
    if (!cleanWord || cleanWord.length <= 1 || cleanWord.split(/\s+/).length > 6) return;

    try {
      const range = selection.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        void handleLookupWordText(cleanWord, rect.left + rect.width / 2, rect.top);
      }
    } catch {
      // Ignore range calculation error
    }
  }, [handleLookupWordText]);

  const handleTranslateMessage = useCallback(async (text: string, messageKey: string) => {
    const cleanText = cleanMarkdownForTts(text);
    if (!cleanText || translations[messageKey]) return;
    setTranslatingKeys((prev) => ({ ...prev, [messageKey]: true }));
    try {
      const res = await translateText({
        text: cleanText,
        source_language: "auto",
        target_language: "zh",
      });
      setTranslations((prev) => ({ ...prev, [messageKey]: res.translated_text }));
    } catch (err) {
      console.error("Translate error:", err);
    } finally {
      setTranslatingKeys((prev) => ({ ...prev, [messageKey]: false }));
    }
  }, [translations]);

  const stableTranslateMessage = useCallback((content: string, key: string) => {
    void handleTranslateMessage(content, key);
  }, [handleTranslateMessage]);

  const renderInteractiveText = useCallback((text: string) => {
    if (!text) return null;
    const tokens = text.split(/(\s+)/);
    return tokens.map((token, index) => {
      const isWord = /^[a-zA-Z0-9'-]+$/.test(token.trim());
      if (isWord) {
        return (
          <span
            key={index}
            className="vsWordInteractive"
            onClick={(e) => void handleWordClick(e, token)}
            title={t("点击查词", "Click to look up word")}
          >
            {token}
          </span>
        );
      }
      return <span key={index}>{token}</span>;
    });
  }, [handleWordClick, t]);

  function handleBodyScroll() {
    const el = bodyRef.current;
    if (!el) return;
    if (isProgrammaticScrollRef.current) {
      isProgrammaticScrollRef.current = false;
      return;
    }
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const threshold = isVoiceActive ? 180 : 140;
    const isNearBottom = distanceFromBottom < threshold;
    shouldStickToBottomRef.current = isNearBottom;
    setShowScrollBottomBtn(!isNearBottom && combinedMessages.length > 0);
  }

  const handleComposerSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    const userText = chat.chatInput.trim();
    const attachments = chat.chatAttachments || [];
    if (!userText && attachments.length === 0) return;

    if (chat.chatProvider === "Tavus") {
      if (onOpenPal) {
        onOpenPal();
      }
      return;
    }
    if (isVoiceActive) {
      voiceChat.sendTextMessage(userText, attachments);
      chat.onInputChange("");
      chat.clearChatAttachments();
    } else if (isVoiceRealtimeModel(chat.chatProvider, chat.chatModel)) {
      voiceChat.startRecordingWithInitialPrompt(userText, attachments);
      chat.onInputChange("");
      chat.clearChatAttachments();
    } else {
      chat.onSubmit(e);
    }
  }, [chat, voiceChat, isVoiceActive, onOpenPal]);

  return (
    <section className={`vsChatWorkspace ${showCanvas ? "hasCanvasPanel" : ""}`} style={{ position: "relative" }}>
      {/* ── Top Bar Controls (Canvas Toggle) ── */}
      <div className="vsChatTopBar">
        <button
          type="button"
          className={`vsChatCanvasToggleBtn ${showCanvas ? "active" : ""}`}
          onClick={() => setShowCanvas((prev) => !prev)}
          title={showCanvas ? t("关闭侧边画布", "Close Canvas") : t("打开侧边画布", "Open Canvas")}
        >
          <PanelRight size={15} />
          <span>{t("画布", "Canvas")}</span>
          {Boolean(canvasCode) && <span className="vsCanvasBadgeDot" />}
        </button>
      </div>

      {/* ── Left Column: Chat Conversation ── */}
      <div className="vsChatMainColumn">
        {/* ── Body ── */}
        <div
          ref={bodyRef}
          className={`vsChatBody ${showWelcome ? "empty" : ""} ${isVoiceActive ? "liveActive" : ""}`}
          onScroll={handleBodyScroll}
        >
        {showWelcome ? (
          /* ═══ EMPTY STATE ═══ */
          <div className="vsChatCentered">
            <div className="vsWelcomeHero">
              <div className="vsWelcomeHeroIcon" aria-hidden="true">
                <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3v18" />
                  <path d="M8 6v12" />
                  <path d="M16 6v12" />
                  <path d="M4 10v4" />
                  <path d="M20 10v4" />
                </svg>
              </div>
              <div>
                <h1 className="vsWelcomeHeroTitle">{t("Echo · 回声", "Echo")}</h1>
                <p className="vsWelcomeHeroSubtitle">{t("开箱即用的实时语音 AI 助手", "Out-of-the-box realtime voice AI assistant")}</p>
              </div>
            </div>

            <form onSubmit={handleComposerSubmit} className="vsComposerWrapCentered">
              <ChatInputBar
                chat={chat}
                voiceChat={voiceChat}
                onOpenSettings={onOpenSettings}
                onOpenPal={onOpenPal}
              />
            </form>

            <p className="vsChatDisclaimer">{t("AI 生成内容可能存在误差。", "AI content may contain mistakes.")}</p>
            <ErrorNotice
              message={chat.chatError}
              scope="chat"
              context={{
                ...errorRuntimeContext,
                provider: chat.chatProvider,
                model: chat.chatModel
              }}
            />
            {voiceChat.voiceChatError && (
              <div className="vsVoiceChatErrorSection">
                <h4 className="vsVoiceChatErrorTitle">{t("实时语音", "Realtime Voice")}</h4>
                <ErrorNotice
                  message={voiceChat.voiceChatError}
                  scope="voice_chat"
                  context={{
                    ...errorRuntimeContext,
                    provider: voiceChat.voiceChatProvider,
                    model: voiceChat.voiceChatModel
                  }}
                />
              </div>
            )}
          </div>
        ) : (
          /* ═══ MESSAGE LIST ═══ */
          <div className="vsMessageList" onMouseUp={handleMessageListMouseUp}>
            {combinedMessages.map((msg, idx) => {
              const messageKey = msg.id ?? `${idx}-${msg.role}`;
              return (
                <MessageBubble
                  key={messageKey}
                  msg={msg}
                  messageKey={messageKey}
                  index={idx}
                  chatBusy={chat.chatBusy}
                  isStreamingPlaceholder={
                    chat.chatBusy && idx === chat.chatMessages.length - 1 && msg.role === "assistant"
                  }
                  isThinkingActive={
                    chat.chatBusy && idx === combinedMessages.length - 1 && !msg.content
                  }
                  copied={copiedMessageKey === messageKey}
                  playing={playingMessageKey === messageKey}
                  loadingTts={loadingTtsMessageKey === messageKey}
                  sourcesOpen={expandedSourcesKey === messageKey}
                  reasoningCollapsed={Boolean(collapsedReasoningKeys[messageKey])}
                  translation={translations[messageKey]}
                  translating={translatingKeys[messageKey]}
                  t={t}
                  onCopy={stableCopyMessage}
                  onPlayTts={stablePlayTts}
                  onTranslate={stableTranslateMessage}
                  onRegenerate={stableRegenerateMessage}
                  onDelete={stableDeleteMessage}
                  onToggleSources={stableToggleSources}
                  onToggleReasoning={stableToggleReasoning}
                  onOpenInCanvas={handleOpenInCanvas}
                />
              );
            })}

            {/* ── Live Streaming Bubbles ── */}
            {isVoiceActive && voiceChat.voiceChatTranscript && (
              <div className="bubble user live isSpeaking">
                <div className="vsBubbleMeta">
                  <span className="vsStreamingIndicator speaking">
                    {voiceChat.voiceChatLiveTranslate ? t("原文实时转写", "Live source transcript") : t("🎙️ 正在说话中...", "🎙️ Speaking...")}
                  </span>
                </div>
                <p>{renderInteractiveText(voiceChat.voiceChatTranscript)}</p>
                <div className="vsBubbleActions">
                  <button
                    type="button"
                    className={`vsBubbleActionBtn${copiedMessageKey === "live-source" ? " copied" : ""}`}
                    aria-label={copiedMessageKey === "live-source" ? t("已复制", "Copied") : t("复制实时原文", "Copy live source")}
                    title={t("复制实时原文", "Copy live source")}
                    onClick={() => void copyMessage(voiceChat.voiceChatTranscript, "live-source")}
                  >
                    <CopyIcon />
                  </button>
                </div>
              </div>
            )}
            {isVoiceActive && voiceChat.voiceChatAgentToolStatus && (
              <div className="vsVoiceToolStatus" role="status" aria-live="polite">
                <span className="vsPulseDot" aria-hidden="true" />
                <div>
                  <strong>{voiceChat.voiceChatAgentToolStatus}</strong>
                  {voiceChat.voiceChatAgentRunMeta ? <small>{voiceChat.voiceChatAgentRunMeta}</small> : null}
                </div>
              </div>
            )}
            {isVoiceActive && voiceChat.voiceChatAgentSources && voiceChat.voiceChatAgentSources.length > 0 && (
              <div className="vsVoiceToolSources" aria-label={t("工具来源", "Tool sources")}>
                {voiceChat.voiceChatAgentSources.map((source, index) => (
                  <a
                    key={`${source.uri}-${index}`}
                    href={source.uri}
                    target="_blank"
                    rel="noreferrer"
                    title={source.snippet}
                  >
                    {source.title || t(`来源 ${index + 1}`, `Source ${index + 1}`)}
                  </a>
                ))}
              </div>
            )}
            {isVoiceActive && voiceChat.voiceChatReply && (
              <div className="bubble assistant live isReplying">
                <div className="vsBubbleMeta">
                  <span className="vsStreamingIndicator replying">
                    {voiceChat.voiceChatLiveTranslate ? t(`译文：${voiceChat.voiceChatTargetLanguageLabel}`, `Translation: ${voiceChat.voiceChatTargetLanguageLabel}`) : t("🤖 正在回复...", "🤖 Replying...")}
                  </span>
                </div>
                <p>{renderInteractiveText(voiceChat.voiceChatReply)}</p>
                <div className="vsBubbleActions">
                  <button
                    type="button"
                    className={`vsBubbleActionBtn${copiedMessageKey === "live-target" ? " copied" : ""}`}
                    aria-label={copiedMessageKey === "live-target" ? t("已复制", "Copied") : t("复制实时译文", "Copy live translation")}
                    title={t("复制实时译文", "Copy live translation")}
                    onClick={() => void copyMessage(voiceChat.voiceChatReply, "live-target")}
                  >
                    <CopyIcon />
                  </button>
                  {(() => {
                    const match = voiceChat.voiceChatReply.match(/```(?:jsx|tsx|react|javascript|js)?\s*\n([\s\S]*?)```/i);
                    const htmlMatch = voiceChat.voiceChatReply.match(/```(?:html|xml)?\s*\n([\s\S]*?)```/i);
                    const foundCode = match?.[1]?.trim() || htmlMatch?.[1]?.trim();
                    const foundMode = match?.[1]?.trim() ? "react" : "html";
                    if (!foundCode) return null;
                    return (
                      <button
                        type="button"
                        className="vsBubbleActionBtn"
                        aria-label={t("在画布中预览", "Preview on Canvas")}
                        title={t("在画布中预览", "Preview on Canvas")}
                        onClick={() => handleOpenInCanvas(foundCode, foundMode, t("实时语音生成组件", "Live Voice Component"))}
                      >
                        <PanelRight size={14} />
                      </button>
                    );
                  })()}
                </div>
              </div>
            )}
            <div ref={messagesEndRef} style={{ height: 1 }} />
          </div>
        )}
      </div>

      {/* ── Scroll to bottom floating action ── */}
      {showScrollBottomBtn && !showWelcome && (
        <button
          type="button"
          className="vsScrollToBottomBtn"
          onClick={() => scrollToBottom(true)}
          title={t("滚动到最新对话", "Scroll to latest conversation")}
        >
          <ChevronDownIcon />
          <span>{t("最新对话", "Latest")}</span>
        </button>
      )}

      {/* ── Instant Word Lookup Popover Tooltip ── */}
      {wordLookup && (
        <div
          ref={lookupPopoverRef}
          className="vsWordLookupPopover"
          style={{
            left: `${Math.max(20, Math.min(window.innerWidth - 220, wordLookup.x))}px`,
            top: `${Math.max(10, wordLookup.y - 64)}px`,
          }}
        >
          <div className="vsWordLookupHead">
            <span className="vsWordLookupTerm">{wordLookup.word}</span>
            <button
              type="button"
              className="vsWordLookupClose"
              onClick={() => setWordLookup(null)}
              title={t("关闭", "Close")}
            >
              ×
            </button>
          </div>
          <div className="vsWordLookupBody">
            {wordLookup.loading ? (
              <span className="vsWordLookupLoading">{t("正在查询释义...", "Looking up definition...")}</span>
            ) : wordLookup.error ? (
              <span className="vsWordLookupError">{wordLookup.error}</span>
            ) : (
              <span className="vsWordLookupDef">{wordLookup.definition}</span>
            )}
          </div>
        </div>
      )}

      {/* ── Bottom composer ── */}
      {(!showWelcome || isVoiceActive) && (
        <div className={`vsComposerWrap ${isVoiceActive ? "liveActive" : ""}`}>
          <form onSubmit={handleComposerSubmit}>
            <ChatInputBar
              chat={chat}
              voiceChat={voiceChat}
              onOpenSettings={onOpenSettings}
              onOpenPal={onOpenPal}
            />
          </form>

          {!isVoiceActive ? (
            <p className="vsChatDisclaimer">{t("AI 生成内容可能存在误差，请按需核对关键信息。", "AI-generated content may contain mistakes. Verify important details when needed.")}</p>
          ) : null}
          <ErrorNotice
            message={chat.chatError}
            scope="chat"
            context={{
              ...errorRuntimeContext,
              provider: chat.chatProvider,
              model: chat.chatModel
            }}
          />
          {ttsPlaybackError && (
            <div className="vsTtsErrorSection" style={{ marginTop: 8 }}>
              <ErrorNotice
                message={ttsPlaybackError}
                scope="tts"
                context={errorRuntimeContext as Record<string, string | number | boolean | null | undefined>}
              />
            </div>
          )}
          {voiceChat.voiceChatError && (
            <div className="vsVoiceChatErrorSection">
              <h4 className="vsVoiceChatErrorTitle">{t("实时语音", "Realtime Voice")}</h4>
              <ErrorNotice
                message={voiceChat.voiceChatError}
                scope="voice_chat"
                context={{
                  ...errorRuntimeContext,
                  provider: voiceChat.voiceChatProvider,
                  model: voiceChat.voiceChatModel
                }}
              />
            </div>
          )}
        </div>
      )}
      </div>

      {/* ── Right Column: Visual Canvas Side Panel ── */}
      {showCanvas && (
        <aside className="vsChatCanvasSidePanel">
          <div className="vsCanvasToolbar">
            <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
              <span style={{ fontWeight: 600, fontSize: "13px", color: "var(--text-primary)", whiteSpace: "nowrap" }}>
                🎨 {canvasTitle || t("实时画布", "Realtime Canvas")}
              </span>
              <div className="vsCanvasModeToggle">
                <button
                  type="button"
                  onClick={() => setCanvasMode("react")}
                  style={{
                    padding: "2px 8px",
                    border: "none",
                    borderRadius: "4px",
                    background: canvasMode === "react" ? "var(--surface-strong)" : "transparent",
                    cursor: "pointer",
                    fontSize: "11px",
                    fontWeight: canvasMode === "react" ? 600 : 400,
                    color: "var(--text-primary)",
                  }}
                >
                  React
                </button>
                <button
                  type="button"
                  onClick={() => setCanvasMode("html")}
                  style={{
                    padding: "2px 8px",
                    border: "none",
                    borderRadius: "4px",
                    background: canvasMode === "html" ? "var(--surface-strong)" : "transparent",
                    cursor: "pointer",
                    fontSize: "11px",
                    fontWeight: canvasMode === "html" ? 600 : 400,
                    color: "var(--text-primary)",
                  }}
                >
                  HTML
                </button>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div className="vsCanvasViewToggle">
                <button
                  type="button"
                  onClick={() => setCanvasView("preview")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "4px 8px",
                    border: "none",
                    background: canvasView === "preview" ? "var(--brand-soft)" : "transparent",
                    color: canvasView === "preview" ? "var(--brand-dark)" : "var(--text-secondary)",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "12px",
                  }}
                  title={t("预览视图", "Preview view")}
                >
                  <Monitor size={13} /> {t("预览", "Preview")}
                </button>
                <button
                  type="button"
                  onClick={() => setCanvasView("code")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "4px 8px",
                    border: "none",
                    background: canvasView === "code" ? "var(--brand-soft)" : "transparent",
                    color: canvasView === "code" ? "var(--brand-dark)" : "var(--text-secondary)",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "12px",
                  }}
                  title={t("代码视图", "Code view")}
                >
                  <Code2 size={13} /> {t("代码", "Code")}
                </button>
              </div>

              {Boolean(canvasCode) && (
                <button
                  type="button"
                  onClick={() => setCanvasCode("")}
                  style={{
                    padding: "4px 6px",
                    border: "none",
                    background: "transparent",
                    borderRadius: "4px",
                    cursor: "pointer",
                    color: "var(--text-secondary)",
                  }}
                  title={t("清空画布", "Clear Canvas")}
                >
                  <Trash2 size={14} />
                </button>
              )}

              <button
                type="button"
                onClick={() => setShowCanvas(false)}
                style={{
                  padding: "4px 6px",
                  border: "none",
                  background: "transparent",
                  borderRadius: "4px",
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                }}
                title={t("关闭", "Close")}
              >
                <X size={16} />
              </button>
            </div>
          </div>

          <div style={{ flex: 1, overflow: "hidden", position: "relative", display: "flex", flexDirection: "column" }}>
            {!canvasCode ? (
              <div
                className="vsCanvasEmptyState"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  color: "var(--text-secondary)",
                  padding: "24px",
                  textAlign: "center",
                  gap: "14px",
                }}
              >
                <Monitor size={44} opacity={0.3} />
                <div>
                  <h4 style={{ margin: "0 0 6px", color: "var(--text-primary)", fontSize: "14px" }}>
                    {t("实时语音画布已就绪", "Realtime Voice Canvas Ready")}
                  </h4>
                  <p style={{ margin: 0, fontSize: "12px", maxWidth: "280px", lineHeight: "1.5" }}>
                    {t(
                      "在语音通话中直接对 Gemini 说「在画布上做一个...」或「帮我写一个登录卡片」，画布会实时展示生成的组件！",
                      "Tell Gemini in voice 'Draw a card on the canvas' or 'Build a login widget', and the canvas will render it live!"
                    )}
                  </p>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", justifyContent: "center", maxWidth: "300px" }}>
                  {[
                    { label: "登录表单", en: "Login Card", prompt: "请帮我在画布上做一个漂亮的 React 登录卡片组件" },
                    { label: "待办清单", en: "Todo List", prompt: "请帮我在画布上做一个交互式 React 待办事项组件" },
                    { label: "数据仪表盘", en: "Dashboard", prompt: "请帮我在画布上做一个包含数据卡片的仪表盘组件" },
                    { label: "计数器游戏", en: "Counter Game", prompt: "请帮我在画布上做一个趣味点击计数器小游戏" },
                  ].map((chip) => (
                    <button
                      key={chip.label}
                      type="button"
                      onClick={() => {
                        if (isVoiceActive) {
                          voiceChat.sendTextMessage(chip.prompt);
                        } else {
                          chat.onInputChange(chip.prompt);
                        }
                      }}
                      style={{
                        padding: "4px 10px",
                        fontSize: "11px",
                        borderRadius: "14px",
                        border: "1px solid var(--border-color)",
                        background: "var(--bg-card)",
                        color: "var(--text-primary)",
                        cursor: "pointer",
                      }}
                    >
                      + {t(chip.label, chip.en)}
                    </button>
                  ))}
                </div>
              </div>
            ) : canvasView === "preview" ? (
              <CanvasPreview code={canvasCode} mode={canvasMode} />
            ) : (
              <CanvasCodeView code={canvasCode} onCopy={() => copyTextToClipboard(canvasCode)} />
            )}
          </div>
        </aside>
      )}
    </section>
  );
}
