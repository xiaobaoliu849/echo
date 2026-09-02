import React, { useState, useEffect, useRef } from "react";
import type { UseVoiceChatResult } from "../../hooks/useVoiceChat";
import { useI18n } from "../../i18n";
import { translateText } from "../../api";

type Props = {
  voiceChat: UseVoiceChatResult;
  isOpen: boolean;
  onToggle: () => void;
};

/* ── Inline SVG Icons ── */
const CopyIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>
);
const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
);
const TranslateIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 8 6 6"></path><path d="m4 14 6-6 2-3"></path><path d="M2 5h12"></path><path d="M7 2h1"></path><path d="m22 22-5-10-5 10"></path><path d="M14 18h6"></path></svg>
);
const CloseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
);

type WordLookupState = {
  word: string;
  definition?: string;
  loading: boolean;
  error?: string;
  x: number;
  y: number;
};

export default function LiveCaptionDrawer({ voiceChat, isOpen, onToggle }: Props) {
  const { t } = useI18n();
  const [fontSize, setFontSize] = useState<"normal" | "large">("normal");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [wordLookup, setWordLookup] = useState<WordLookupState | null>(null);
  const [sentenceTranslations, setSentenceTranslations] = useState<Record<string, string>>({});
  const [translatingKeys, setTranslatingKeys] = useState<Record<string, boolean>>({});

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const lookupPopoverRef = useRef<HTMLDivElement>(null);

  const isLiveTranslate = voiceChat.voiceChatLiveTranslate;
  const targetLang = voiceChat.voiceChatTargetLanguageLabel || "中文";

  // Auto-scroll to bottom when new stream transcript/reply arrives
  useEffect(() => {
    if (!isOpen) return;
    const container = scrollContainerRef.current;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [isOpen, voiceChat.voiceChatTranscript, voiceChat.voiceChatReply, voiceChat.sessionSummary]);

  // Close word lookup on click outside or Escape
  useEffect(() => {
    if (!wordLookup) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (lookupPopoverRef.current && !lookupPopoverRef.current.contains(e.target as Node)) {
        setWordLookup(null);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setWordLookup(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [wordLookup]);

  const handleCopy = async (text: string, key: string) => {
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1800);
    } catch (err) {
      console.error("Failed to copy text:", err);
    }
  };

  const handleWordClick = async (e: React.MouseEvent<HTMLSpanElement>, rawWord: string) => {
    e.stopPropagation();
    const cleanWord = rawWord.replace(/^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$/g, "").trim();
    if (!cleanWord || cleanWord.length <= 1) return;

    const rect = e.currentTarget.getBoundingClientRect();
    setWordLookup({
      word: cleanWord,
      loading: true,
      x: rect.left + rect.width / 2,
      y: rect.top,
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
    } catch (err) {
      setWordLookup((prev) =>
        prev && prev.word === cleanWord
          ? { ...prev, error: t("查词失败", "Lookup failed"), loading: false }
          : prev
      );
    }
  };

  const handleTranslateSentence = async (text: string, key: string) => {
    if (!text.trim() || sentenceTranslations[key]) return;
    setTranslatingKeys((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await translateText({
        text,
        source_language: "auto",
        target_language: "zh",
      });
      setSentenceTranslations((prev) => ({ ...prev, [key]: res.translated_text }));
    } catch (err) {
      console.error("Failed to translate sentence:", err);
    } finally {
      setTranslatingKeys((prev) => ({ ...prev, [key]: false }));
    }
  };

  // Helper to render interactive words (for English practice / IELTS)
  const renderInteractiveText = (text: string) => {
    if (!text) return null;
    const tokens = text.split(/(\s+)/);
    return tokens.map((token, index) => {
      const isWord = /^[a-zA-Z0-9'-]+$/.test(token.trim());
      if (isWord) {
        return (
          <span
            key={index}
            className="vsCaptionInteractiveWord"
            onClick={(e) => handleWordClick(e, token)}
            title={t("点击查词", "Click to translate word")}
          >
            {token}
          </span>
        );
      }
      return <span key={index}>{token}</span>;
    });
  };

  if (!isOpen) return null;

  const pastMessages = voiceChat.sessionSummary || [];
  const hasLiveSource = Boolean(voiceChat.voiceChatTranscript);
  const hasLiveReply = Boolean(voiceChat.voiceChatReply);
  const isEmpty = pastMessages.length === 0 && !hasLiveSource && !hasLiveReply;

  return (
    <div className={`vsLiveCaptionDrawer ${fontSize === "large" ? "vsFontLarge" : ""}`} role="region" aria-label={t("实时字幕抽屉", "Live Caption Drawer")}>
      {/* ── Top Header Toolbar ── */}
      <div className="vsLiveCaptionHeader">
        <div className="vsCaptionHeaderLeft">
          <span className="vsCaptionBadge">
            <span className="vsCaptionLivePulse" />
            {isLiveTranslate ? t(`同声传译 · ${targetLang}`, `Live Translate · ${targetLang}`) : t("实时双语字幕", "Live Captions")}
          </span>
          <span className="vsCaptionSubHint">
            {t("点词即查 · 实时流式对齐", "Click word to look up · Live stream aligned")}
          </span>
        </div>

        <div className="vsCaptionHeaderRight">
          <button
            type="button"
            className={`vsCaptionToolBtn ${fontSize === "large" ? "active" : ""}`}
            onClick={() => setFontSize((prev) => (prev === "normal" ? "large" : "normal"))}
            title={fontSize === "normal" ? t("切换为大字号", "Switch to large font") : t("切换为标准字号", "Switch to standard font")}
            aria-label={t("字幕字号切换", "Toggle font size")}
          >
            <span style={{ fontSize: fontSize === "large" ? "14px" : "11px", fontWeight: "bold" }}>A</span>
          </button>

          <button
            type="button"
            className="vsCaptionToolBtn"
            onClick={onToggle}
            title={t("收起字幕 (C)", "Hide captions (C)")}
            aria-label={t("收起字幕", "Hide captions")}
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      {/* ── Subtitle Content Scroll Body ── */}
      <div className="vsLiveCaptionBody" ref={scrollContainerRef}>
        {isEmpty ? (
          <div className="vsCaptionEmptyNotice">
            <span className="vsCaptionEmptyIcon">🎙️</span>
            <p>{t("等待语音输入中... 开始说话，字幕将在此实时逐字显示与对照", "Listening for speech... Start speaking and captions will stream here in real time.")}</p>
          </div>
        ) : (
          <div className="vsCaptionList">
            {/* ── Render Past Session Messages ── */}
            {pastMessages.map((msg, index) => {
              if (msg.role !== "user" && msg.role !== "assistant") return null;
              const isUser = msg.role === "user";
              const key = `hist-${index}`;
              const translation = sentenceTranslations[key];
              const isTranslating = translatingKeys[key];

              return (
                <div key={key} className={`vsCaptionItem ${isUser ? "user" : "assistant"}`}>
                  <div className="vsCaptionSpeakerTag">
                    <span className={`vsSpeakerDot ${isUser ? "user" : "assistant"}`} />
                    <span className="vsSpeakerLabel">{isUser ? t("我", "You") : t("Echo", "Echo")}</span>
                  </div>

                  <div className="vsCaptionTextWrapper">
                    <div className="vsCaptionOriginalText">
                      {renderInteractiveText(msg.content)}
                    </div>

                    {translation && (
                      <div className="vsCaptionTranslationText">
                        <span className="vsCaptionTransLabel">🌐 {t("译文", "Translation")}:</span>
                        <span>{translation}</span>
                      </div>
                    )}
                  </div>

                  <div className="vsCaptionItemActions">
                    {!isUser && !translation && (
                      <button
                        type="button"
                        className="vsCaptionActionIconBtn"
                        disabled={isTranslating}
                        onClick={() => handleTranslateSentence(msg.content, key)}
                        title={t("翻译整句", "Translate sentence")}
                      >
                        <TranslateIcon />
                      </button>
                    )}
                    <button
                      type="button"
                      className={`vsCaptionActionIconBtn ${copiedKey === key ? "copied" : ""}`}
                      onClick={() => handleCopy(msg.content, key)}
                      title={t("复制此句", "Copy sentence")}
                    >
                      {copiedKey === key ? <CheckIcon /> : <CopyIcon />}
                    </button>
                  </div>
                </div>
              );
            })}

            {/* ── Render Active Live User Input ── */}
            {hasLiveSource && (
              <div className="vsCaptionItem user liveStreaming">
                <div className="vsCaptionSpeakerTag">
                  <span className="vsSpeakerDot user breathing" />
                  <span className="vsSpeakerLabel">{t("我 (正在说...)", "You (Speaking...)")}</span>
                </div>
                <div className="vsCaptionTextWrapper">
                  <div className="vsCaptionOriginalText streaming">
                    {renderInteractiveText(voiceChat.voiceChatTranscript)}
                  </div>
                </div>
                <div className="vsCaptionItemActions">
                  <button
                    type="button"
                    className={`vsCaptionActionIconBtn ${copiedKey === "live-user" ? "copied" : ""}`}
                    onClick={() => handleCopy(voiceChat.voiceChatTranscript, "live-user")}
                    title={t("复制当前原话", "Copy live speech")}
                  >
                    {copiedKey === "live-user" ? <CheckIcon /> : <CopyIcon />}
                  </button>
                </div>
              </div>
            )}

            {/* ── Render Active Live AI Reply ── */}
            {hasLiveReply && (
              <div className="vsCaptionItem assistant liveStreaming">
                <div className="vsCaptionSpeakerTag">
                  <span className="vsSpeakerDot assistant pulsing" />
                  <span className="vsSpeakerLabel">{t("Echo (正在回复...)", "Echo (Replying...)")}</span>
                </div>
                <div className="vsCaptionTextWrapper">
                  <div className="vsCaptionOriginalText streaming">
                    {renderInteractiveText(voiceChat.voiceChatReply)}
                  </div>

                  {sentenceTranslations["live-reply"] && (
                    <div className="vsCaptionTranslationText">
                      <span className="vsCaptionTransLabel">🌐 {t("译文", "Translation")}:</span>
                      <span>{sentenceTranslations["live-reply"]}</span>
                    </div>
                  )}
                </div>
                <div className="vsCaptionItemActions">
                  {!sentenceTranslations["live-reply"] && (
                    <button
                      type="button"
                      className="vsCaptionActionIconBtn"
                      disabled={translatingKeys["live-reply"]}
                      onClick={() => handleTranslateSentence(voiceChat.voiceChatReply, "live-reply")}
                      title={t("翻译当前回复", "Translate reply")}
                    >
                      <TranslateIcon />
                    </button>
                  )}
                  <button
                    type="button"
                    className={`vsCaptionActionIconBtn ${copiedKey === "live-reply" ? "copied" : ""}`}
                    onClick={() => handleCopy(voiceChat.voiceChatReply, "live-reply")}
                    title={t("复制当前回复", "Copy live reply")}
                  >
                    {copiedKey === "live-reply" ? <CheckIcon /> : <CopyIcon />}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Instant Word Lookup Popover Tooltip ── */}
      {wordLookup && (
        <div
          ref={lookupPopoverRef}
          className="vsCaptionWordPopover"
          style={{
            left: `${Math.max(20, Math.min(window.innerWidth - 220, wordLookup.x))}px`,
            top: `${Math.max(10, wordLookup.y - 64)}px`,
          }}
        >
          <div className="vsWordPopoverHead">
            <span className="vsWordPopoverTerm">{wordLookup.word}</span>
            <button
              type="button"
              className="vsWordPopoverClose"
              onClick={() => setWordLookup(null)}
              title={t("关闭", "Close")}
            >
              ×
            </button>
          </div>
          <div className="vsWordPopoverBody">
            {wordLookup.loading ? (
              <span className="vsWordLoading">{t("正在查询释义...", "Looking up definition...")}</span>
            ) : wordLookup.error ? (
              <span className="vsWordError">{wordLookup.error}</span>
            ) : (
              <span className="vsWordDef">{wordLookup.definition}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
