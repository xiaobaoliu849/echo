import React, { useState, useEffect, useRef, useMemo } from "react";
import { extractPdfText } from "../../api";
import VoiceCallSettingsPopover from "../VoiceCallSettingsPopover";
import { isVoiceRealtimeModel } from "../../hooks/useChat";
import { formatVoiceChatSecondaryLabel } from "../../hooks/useVoiceChatHelpers";
import type { UseChatResult } from "../../hooks/useChat";
import type { UseVoiceChatResult } from "../../hooks/useVoiceChat";
import { useI18n } from "../../i18n";

type Props = {
  chat: UseChatResult;
  voiceChat: UseVoiceChatResult;
  onOpenSettings?: () => void;
  onOpenPal?: () => void;
};

/* ── Inline SVG icons ── */
const PaperclipIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>
);
const MicIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>
);
const MicOnIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>
);
const MicOffIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="2" x2="22" y1="2" y2="22"></line><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"></path><path d="M5 10v2a7 7 0 0 0 12 5"></path><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"></path><path d="M9 9v3a3 3 0 0 0 5.12 2.12"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>
);
const PhoneIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.78 19.78 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.78 19.78 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.77.62 2.6a2 2 0 0 1-.45 2.11L8.09 9.62a16 16 0 0 0 6.29 6.29l1.19-1.19a2 2 0 0 1 2.11-.45c.83.29 1.7.5 2.6.62A2 2 0 0 1 22 16.92Z"></path></svg>
);
const PhoneOffIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-3.33-2.67m-2.67-3.34a19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91"></path><line x1="22" x2="2" y1="2" y2="22"></line></svg>
);
const VideoIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.934a.5.5 0 0 0-.777-.416L16 11"></path><rect width="14" height="12" x="2" y="6" rx="2"></rect></svg>
);
const SendIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3.714 3.048a.498.498 0 0 0-.683.627l2.843 7.627a2 2 0 0 1 0 1.396l-2.842 7.627a.498.498 0 0 0 .682.627l18.168-8.215a.5.5 0 0 0 0-.904z"></path><line x1="6" x2="11" y1="12" y2="12"></line></svg>
);
const SpinnerIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="vsSpin"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
);

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

type SpeechRecognitionResultLike = {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
};

type SpeechRecognitionEventLike = Event & {
  readonly resultIndex: number;
  readonly results: ArrayLike<SpeechRecognitionResultLike>;
};

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
};

export default function ChatInputBar({ chat, voiceChat, onOpenSettings, onOpenPal }: Props) {
  const { t } = useI18n();
  const isVoiceActive = voiceChat.voiceChatRecording || voiceChat.voiceChatConnected;
  const hasInput = chat.chatInput.trim().length > 0;
  const hasAttachments = (chat.chatAttachments && chat.chatAttachments.length > 0);
  const canSend = hasInput || hasAttachments;
  const isRealtime = isVoiceRealtimeModel(chat.chatProvider, chat.chatModel);
  const isLiveTranslate = voiceChat.voiceChatLiveTranslate;

  const [dictating, setDictating] = useState(false);
  const [dictationError, setDictationError] = useState("");
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  // Keyboard shortcut: 'M' to toggle mute during active live voice calls
  useEffect(() => {
    if (!isVoiceActive) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isEditingText = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (isEditingText && !e.altKey && !e.ctrlKey && !e.metaKey) return;
      if (e.key === "m" || e.key === "M") {
        e.preventDefault();
        voiceChat.onToggleMute?.();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isVoiceActive, voiceChat]);

  const isAssistantSpeaking = Boolean(voiceChat.voiceChatAssistantSpeaking || voiceChat.voiceChatReply);
  const isUserSpeaking = !isAssistantSpeaking && Boolean(voiceChat.voiceChatTranscript);
  const isThinking = !isAssistantSpeaking && !isUserSpeaking && Boolean(voiceChat.voiceChatBusy);

  // Determine conversational state for visualizer
  const visualizerState = useMemo(() => {
    if (voiceChat.voiceChatMuted) return "state-muted";
    if (isAssistantSpeaking) return "state-replying";
    if (isUserSpeaking) return "state-listening";
    if (isThinking) return "state-thinking";
    return "state-listening";
  }, [voiceChat.voiceChatMuted, isAssistantSpeaking, isUserSpeaking, isThinking]);

  // Soundwave visualizer requestAnimationFrame animation loop (12 bars, symmetric)
  useEffect(() => {
    if (!voiceChat.voiceChatConnected) return;

    const micAnalyser = voiceChat.micAnalyser;
    const assistantAnalyser = voiceChat.assistantAnalyser;

    if (!micAnalyser && !assistantAnalyser) return;

    let animationFrameId: number;
    const micDataArray = micAnalyser ? new Uint8Array(micAnalyser.frequencyBinCount) : null;
    const assistantDataArray = assistantAnalyser ? new Uint8Array(assistantAnalyser.frequencyBinCount) : null;

    // Symmetrical bar distribution indices for 12 bars
    const symmetricIndices = [0, 2, 4, 6, 8, 10, 11, 9, 7, 5, 3, 1];

    const updateVisualizer = () => {
      let micVolume = 0;
      let assistantVolume = 0;

      if (micAnalyser && micDataArray && !voiceChat.voiceChatMuted) {
        micAnalyser.getByteFrequencyData(micDataArray);
        let sum = 0;
        for (let i = 0; i < micDataArray.length; i++) {
          sum += micDataArray[i];
        }
        micVolume = sum / micDataArray.length;
      }

      if (assistantAnalyser && assistantDataArray) {
        assistantAnalyser.getByteFrequencyData(assistantDataArray);
        let sum = 0;
        for (let i = 0; i < assistantDataArray.length; i++) {
          sum += assistantDataArray[i];
        }
        assistantVolume = sum / assistantDataArray.length;
      }

      const visualizerEl = document.getElementById("vs-voice-visualizer");
      if (visualizerEl) {
        const isAssistantActive = isAssistantSpeaking || assistantVolume > 1.5;
        const activeVolume = isAssistantActive ? assistantVolume : (voiceChat.voiceChatMuted ? 0 : micVolume);
        const dataArray = isAssistantActive ? assistantDataArray : (voiceChat.voiceChatMuted ? null : micDataArray);

        const glowEl = visualizerEl.querySelector(".vsVoiceGlow") as HTMLElement;
        if (glowEl) {
          if (voiceChat.voiceChatMuted) {
            glowEl.style.transform = "scale(0.8)";
            glowEl.style.opacity = "0";
          } else {
            const scale = 0.85 + (activeVolume / 255) * 0.65;
            const opacity = 0.35 + (activeVolume / 255) * 0.65;
            glowEl.style.transform = `scale(${scale})`;
            glowEl.style.opacity = `${opacity}`;
          }
        }

        const bars = visualizerEl.querySelectorAll(".vsWaveBar");
        if (!voiceChat.voiceChatMuted && activeVolume > 2 && dataArray && bars.length > 0) {
          bars.forEach((bar, index) => {
            const sampleIdx = symmetricIndices[index % symmetricIndices.length] || 0;
            const val = dataArray[sampleIdx] || 0;
            const height = 18 + (val / 255) * 82;
            (bar as HTMLElement).style.height = `${height}%`;
          });
        } else {
          bars.forEach((bar) => {
            (bar as HTMLElement).style.height = "";
          });
          if (glowEl && !voiceChat.voiceChatMuted) {
            glowEl.style.transform = "";
            glowEl.style.opacity = "";
          }
        }
      }

      animationFrameId = requestAnimationFrame(updateVisualizer);
    };

    const timerId = setTimeout(() => {
      updateVisualizer();
    }, 100);

    return () => {
      clearTimeout(timerId);
      cancelAnimationFrame(animationFrameId);
    };
  }, [voiceChat.voiceChatConnected, voiceChat.voiceChatMuted, isAssistantSpeaking, voiceChat.micAnalyser, voiceChat.assistantAnalyser]);

  function appendDictationText(text: string) {
    const clean = text.trim();
    if (!clean) return;
    const current = chat.chatInput.trimEnd();
    chat.onInputChange(current ? `${current} ${clean}` : clean);
  }

  function toggleDictation() {
    if (dictating) {
      recognitionRef.current?.stop();
      setDictating(false);
      return;
    }
    const speechWindow = window as SpeechRecognitionWindow;
    const SpeechRecognitionCtor = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) {
      setDictationError(t(
        "当前桌面壳不支持语音转文字。请在 Edge/Chrome 网页版使用麦克风转写，或直接点击实时通话按钮。",
        "Speech-to-text dictation is not supported in this shell. Use Edge/Chrome in the browser, or start a realtime call."
      ));
      return;
    }
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) {
          finalText += result[0]?.transcript || "";
        }
      }
      appendDictationText(finalText);
    };
    recognition.onerror = (event) => {
      setDictationError(t(
        `语音转文字失败：${event.error || "未知错误"}`,
        `Speech-to-text failed: ${event.error || "Unknown error"}`
      ));
      setDictating(false);
    };
    recognition.onend = () => setDictating(false);
    recognitionRef.current = recognition;
    setDictationError("");
    setDictating(true);
    recognition.start();
  }

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [parsingFiles, setParsingFiles] = useState<string[]>([]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
      const isImg = file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(file.name);

      if (isImg) {
        const reader = new FileReader();
        reader.onload = (event) => {
          const dataUrl = event.target?.result as string;
          chat.addChatAttachment({
            name: file.name,
            content: "[Image]",
            type: "image",
            mimeType: file.type || "image/jpeg",
            dataUrl,
            size: file.size,
          });
        };
        reader.onerror = (event) => {
          console.error("Failed to read image file:", event);
          alert(t("读取图片失败：", "Failed to read image file: ") + file.name);
        };
        reader.readAsDataURL(file);
      } else if (isPdf) {
        setParsingFiles((prev) => [...prev, file.name]);
        try {
          const res = await extractPdfText(file);
          if (res && res.text) {
            chat.addChatAttachment({
              name: file.name,
              content: res.text,
              type: "pdf",
              size: file.size,
            });
          } else {
            alert(t("PDF 提取内容为空。", "Extracted PDF content is empty."));
          }
        } catch (err) {
          console.error(err);
          alert(t("PDF 文本提取失败：", "Failed to extract text from PDF: ") + (err instanceof Error ? err.message : String(err)));
        } finally {
          setParsingFiles((prev) => prev.filter((name) => name !== file.name));
        }
      } else {
        const reader = new FileReader();
        reader.onload = (event) => {
          const text = event.target?.result;
          if (typeof text === "string") {
            chat.addChatAttachment({
              name: file.name,
              content: text,
              type: "text",
              size: file.size,
            });
          }
        };
        reader.onerror = (event) => {
          console.error("Failed to read file:", event);
          alert(t("读取文件失败：", "Failed to read file: ") + file.name);
        };
        reader.readAsText(file);
      }
    }
    e.target.value = "";
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = (event) => {
            const dataUrl = event.target?.result as string;
            chat.addChatAttachment({
              name: file.name || `image-${Date.now()}.png`,
              content: "[Image]",
              type: "image",
              mimeType: file.type || "image/jpeg",
              dataUrl,
              size: file.size,
            });
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  const placeholder = isVoiceActive
    ? t("正在实时通话中：可直接说话，或输入文字/粘贴图片发送...", "Live call active: speak freely, or type text / paste images to send...")
    : isRealtime
      ? t("输入文字发送启动实时会话，或点击右侧电话按钮通话...", "Type to start realtime chat, or click the phone button to call...")
      : t("输入聊天内容，或者点击右侧麦克风语音转写...", "Type to chat, or click the microphone on the right to dictate...");

  return (
    <div className={`vsComposer ${isVoiceActive ? "liveActive" : ""}`}>
      {/* ── Live Voice Dynamic Call Capsule Banner ── */}
      {isVoiceActive && (
        <div className="vsLiveVoiceStatusBanner">
          <div className="vsVoiceStatusSection">
            <span className="vsVoiceStatusText">
              <span
                className={`vsVoiceStatusDot ${
                  voiceChat.voiceChatMuted
                    ? "muted"
                    : voiceChat.voiceChatConnected
                      ? (isAssistantSpeaking
                          ? "replying"
                          : (isUserSpeaking
                              ? "listening"
                              : (isThinking ? "thinking" : "connected")))
                      : "connecting"
                }`}
              />
              {voiceChat.voiceChatMuted
                ? t("已静音", "Muted")
                : voiceChat.voiceChatConnected
                  ? (isAssistantSpeaking
                      ? t("正在回复...", "Replying...")
                      : (isUserSpeaking
                          ? t("正在聆听...", "Listening...")
                          : (isThinking
                              ? t("正在思考...", "Thinking...")
                              : t("已连接，您可以说话或打字", "Connected: speak or type freely"))))
                  : t("正在建立安全连接...", "Connecting live session...")}
            </span>

            {voiceChat.voiceChatConnected && (
              <span className="vsVoiceTimerBadge" title={t("通话时长", "Call Duration")}>
                <span className="vsVoiceTimerDot" />
                {formatDuration(voiceChat.voiceChatDuration || 0)}
              </span>
            )}
          </div>

          <div className={`vsVoiceVisualizerContainer ${visualizerState}`} id="vs-voice-visualizer">
            <div className="vsVoiceVisualizerWave">
              <div className="vsWaveBar bar-1"></div>
              <div className="vsWaveBar bar-2"></div>
              <div className="vsWaveBar bar-3"></div>
              <div className="vsWaveBar bar-4"></div>
              <div className="vsWaveBar bar-5"></div>
              <div className="vsWaveBar bar-6"></div>
              <div className="vsWaveBar bar-7"></div>
              <div className="vsWaveBar bar-8"></div>
              <div className="vsWaveBar bar-9"></div>
              <div className="vsWaveBar bar-10"></div>
              <div className="vsWaveBar bar-11"></div>
              <div className="vsWaveBar bar-12"></div>
            </div>
            <div className="vsVoiceGlow"></div>
          </div>

          <div className="vsVoiceControlsGroup">
            <button
              type="button"
              className={`vsVoiceCallMuteBtn ${voiceChat.voiceChatMuted ? "muted" : ""}`}
              onClick={voiceChat.onToggleMute}
              title={voiceChat.voiceChatMuted ? t("取消静音 (M)", "Unmute mic (M)") : t("静音麦克风 (M)", "Mute mic (M)")}
              aria-label={voiceChat.voiceChatMuted ? t("取消静音", "Unmute mic") : t("静音麦克风", "Mute mic")}
            >
              {voiceChat.voiceChatMuted ? <MicOffIcon /> : <MicOnIcon />}
              <span>{voiceChat.voiceChatMuted ? t("已静音", "Muted") : t("静音", "Mute")}</span>
            </button>

            <button
              type="button"
              className="vsVoiceCallHangupMiniBtn"
              onClick={() => void voiceChat.onToggleRecording()}
              title={t("挂断实时通话", "Hang up call")}
              aria-label={t("挂断实时通话", "Hang up call")}
            >
              <PhoneOffIcon />
              <span>{t("挂断", "Hang up")}</span>
            </button>
          </div>
        </div>
      )}

      {/* ── Input Box (Always active) ── */}
      <textarea
        rows={1}
        value={chat.chatInput}
        onChange={(e) => chat.onInputChange(e.target.value)}
        onPaste={handlePaste}
        placeholder={placeholder}
        onKeyDown={chat.onComposerKeyDown}
      />
      {dictationError ? <div className="vsComposerInlineHint">{dictationError}</div> : null}

      {/* ── Attachment Preview Section ── */}
      {((chat.chatAttachments && chat.chatAttachments.length > 0) || parsingFiles.length > 0) && (
        <div className="vsComposerAttachments">
          {chat.chatAttachments?.map((att, index) => {
            const isImage = att.type === "image" || att.dataUrl?.startsWith("data:image/") || /\.(png|jpe?g|webp|gif)$/i.test(att.name);
            const imgSrc = att.dataUrl || att.url;
            return isImage && imgSrc ? (
              <div key={`${index}-${att.name}`} className="vsAttachmentImagePill">
                <img src={imgSrc} alt={att.name} className="vsAttachmentThumb" />
                <span className="vsAttachmentPillName" title={att.name}>{att.name}</span>
                <button
                  type="button"
                  className="vsAttachmentPillDelete"
                  onClick={() => chat.removeChatAttachment(index)}
                  title={t("删除附件", "Delete attachment")}
                >
                  ×
                </button>
              </div>
            ) : (
              <div key={`${index}-${att.name}`} className="vsAttachmentPill">
                <span className="vsAttachmentPillIcon">{att.type === "pdf" ? "📕" : "📄"}</span>
                <span className="vsAttachmentPillName" title={att.name}>{att.name}</span>
                <button
                  type="button"
                  className="vsAttachmentPillDelete"
                  onClick={() => chat.removeChatAttachment(index)}
                  title={t("删除附件", "Delete attachment")}
                >
                  ×
                </button>
              </div>
            );
          })}
          {parsingFiles.map((name) => (
            <div key={name} className="vsAttachmentPill loading">
              <span className="spinner-mini"></span>
              <span className="vsAttachmentPillName" title={name}>{name}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Toolbar Section ── */}
      <div className="vsComposerToolbar">
        <div className="vsComposerToolbarLeft">
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: "none" }}
            onChange={handleFileChange}
            accept="image/*,.pdf,.txt,.md,.json,.py,.ts,.tsx,.js,.html,.css"
            multiple
          />
          <button
            type="button"
            className="vsToolbarBtn"
            aria-label={t("附件/图片", "Attachment / Image")}
            onClick={() => fileInputRef.current?.click()}
            title={t("添加图片或文件 (支持截图粘贴 Ctrl+V)", "Add images or documents (supports pasting Ctrl+V)")}
          >
            <PaperclipIcon />
          </button>

          {/* Unified provider → model → voice picker (or read-only chip during active call) */}
          {isVoiceActive ? (
            <span
              className="vsVoiceReadOnlyChip"
              title={`${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel} · ${formatVoiceChatSecondaryLabel({
                liveTranslate: voiceChat.voiceChatLiveTranslate,
                voiceCloneEnabled: Boolean(voiceChat.voiceChatEnableVoiceClone),
                translationMode: voiceChat.voiceChatTranslationMode,
                sourceLanguageCode: voiceChat.voiceChatSourceLanguageCode,
                targetLanguageCode: voiceChat.voiceChatTargetLanguageCode,
                voiceLabel: voiceChat.voiceChatVoiceLabel,
                provider: voiceChat.voiceChatProvider,
                model: voiceChat.voiceChatModel,
                t,
              })}`}
            >
              <MicOnIcon />
              <span>
                {voiceChat.voiceChatProvider} / {voiceChat.voiceChatModel} ·{" "}
                {formatVoiceChatSecondaryLabel({
                  liveTranslate: voiceChat.voiceChatLiveTranslate,
                  voiceCloneEnabled: Boolean(voiceChat.voiceChatEnableVoiceClone),
                  translationMode: voiceChat.voiceChatTranslationMode,
                  sourceLanguageCode: voiceChat.voiceChatSourceLanguageCode,
                  targetLanguageCode: voiceChat.voiceChatTargetLanguageCode,
                  voiceLabel: voiceChat.voiceChatVoiceLabel,
                  provider: voiceChat.voiceChatProvider,
                  model: voiceChat.voiceChatModel,
                  t,
                })}
              </span>
            </span>
          ) : (
            <VoiceCallSettingsPopover
              voiceChat={voiceChat}
              chat={chat}
              t={t}
              disabled={false}
              onOpenSettings={onOpenSettings}
            />
          )}
        </div>

        <div className="vsComposerToolbarRight">
          {!isVoiceActive && !isRealtime && (
            <button
              type="button"
              className={`vsToolbarBtn ${dictating ? "recording" : ""}`}
              aria-label={dictating ? t("停止语音转写", "Stop dictation") : t("语音转写", "Dictate")}
              onClick={toggleDictation}
              disabled={chat.chatBusy}
              title={dictating ? t("停止语音转写", "Stop dictation") : t("语音转写到输入框", "Dictate into the input")}
            >
              <MicIcon />
            </button>
          )}

          {!isVoiceActive && (
            <button
              type="button"
              className={`vsComposerCallBtn ${!isRealtime ? "disabled" : ""}`}
              aria-label={
                (chat ? chat.chatProvider : voiceChat.voiceChatProvider) === "Tavus"
                  ? t("开启视频分身", "Video PAL")
                  : t("实时通话", "Realtime call")
              }
              onClick={() => {
                if (!isRealtime) return;
                if ((chat ? chat.chatProvider : voiceChat.voiceChatProvider) === "Tavus") {
                  if (onOpenPal) {
                    onOpenPal();
                  } else {
                    void voiceChat.onToggleRecording();
                  }
                  return;
                }
                void voiceChat.onToggleRecording();
              }}
              disabled={!isRealtime || !voiceChat.voiceChatSupported || voiceChat.voiceChatBusy}
              title={
                !isRealtime
                  ? t(
                      "当前选择的是文本/多模态模型，实时通话请在左侧切换为实时语音模型（如带「实时」徽章的模型）",
                      "Current model is a text/multimodal model. Switch to a realtime voice model on the left to start a call."
                    )
                  : (chat ? chat.chatProvider : voiceChat.voiceChatProvider) === "Tavus"
                    ? t("开启 Tavus 实时视频分身对话", "Start Tavus video PAL conversation")
                    : isLiveTranslate
                      ? t(`实时翻译：${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`, `Live translate: ${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`)
                      : t(`实时通话：${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`, `Realtime call: ${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`)
              }
            >
              {(chat ? chat.chatProvider : voiceChat.voiceChatProvider) === "Tavus" ? <VideoIcon /> : <PhoneIcon />}
            </button>
          )}

          {canSend ? (
            <button
              type="submit"
              className="vsSendBtn"
              disabled={chat.chatBusy}
              aria-label={t("发送", "Send")}
              title={t("发送", "Send")}
            >
              {chat.chatBusy ? <SpinnerIcon /> : <SendIcon />}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
