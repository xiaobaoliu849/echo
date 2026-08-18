import React, { useState, useEffect, useRef } from "react";
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
};

/* ── Inline SVG icons ── */
const PaperclipIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>
);
const MicIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>
);
const StopIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="5" y="5" rx="2"></rect></svg>
);
const PhoneIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.78 19.78 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.78 19.78 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.77.62 2.6a2 2 0 0 1-.45 2.11L8.09 9.62a16 16 0 0 0 6.29 6.29l1.19-1.19a2 2 0 0 1 2.11-.45c.83.29 1.7.5 2.6.62A2 2 0 0 1 22 16.92Z"></path></svg>
);
const SendIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3.714 3.048a.498.498 0 0 0-.683.627l2.843 7.627a2 2 0 0 1 0 1.396l-2.842 7.627a.498.498 0 0 0 .682.627l18.168-8.215a.5.5 0 0 0 0-.904z"></path><line x1="6" x2="11" y1="12" y2="12"></line></svg>
);
const SpinnerIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="vsSpin"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
);

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

export default function ChatInputBar({ chat, voiceChat, onOpenSettings }: Props) {
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

  // Soundwave visualizer requestAnimationFrame animation loop
  useEffect(() => {
    if (!voiceChat.voiceChatConnected) return;

    const micAnalyser = voiceChat.micAnalyser;
    const assistantAnalyser = voiceChat.assistantAnalyser;

    if (!micAnalyser && !assistantAnalyser) return;

    let animationFrameId: number;
    const micDataArray = micAnalyser ? new Uint8Array(micAnalyser.frequencyBinCount) : null;
    const assistantDataArray = assistantAnalyser ? new Uint8Array(assistantAnalyser.frequencyBinCount) : null;

    const updateVisualizer = () => {
      let micVolume = 0;
      let assistantVolume = 0;

      if (micAnalyser && micDataArray) {
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
        const activeVolume = assistantVolume > 0 ? assistantVolume : micVolume;
        const dataArray = assistantVolume > 0 ? assistantDataArray : micDataArray;

        const glowEl = visualizerEl.querySelector(".vsVoiceGlow") as HTMLElement;
        if (glowEl) {
          const scale = 0.9 + (activeVolume / 255) * 0.5;
          const opacity = 0.5 + (activeVolume / 255) * 0.5;
          glowEl.style.transform = `scale(${scale})`;
          glowEl.style.opacity = `${opacity}`;
        }

        const bars = visualizerEl.querySelectorAll(".vsWaveBar");
        if (activeVolume > 2 && dataArray && bars.length > 0) {
          const step = Math.floor(dataArray.length / bars.length) || 1;
          bars.forEach((bar, index) => {
            const val = dataArray[index * step] || 0;
            const height = 15 + (val / 255) * 85;
            (bar as HTMLElement).style.height = `${height}%`;
          });
        } else {
          bars.forEach((bar) => {
            (bar as HTMLElement).style.height = "";
          });
          if (glowEl) {
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
  }, [voiceChat.voiceChatConnected, voiceChat.micAnalyser, voiceChat.assistantAnalyser]);

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
      {/* ── Live Voice Top Status Banner during active call ── */}
      {isVoiceActive && (
        <div className="vsLiveVoiceStatusBanner">
          <div className="vsVoiceStatusSection">
            <span className="vsVoiceStatusText">
              <span className={`vsVoiceStatusDot ${voiceChat.voiceChatConnected ? "connected" : "connecting"}`} />
              {voiceChat.voiceChatConnected
                ? (voiceChat.voiceChatReply
                    ? t("正在回复...", "Replying...")
                    : (voiceChat.voiceChatTranscript
                        ? t("正在聆听...", "Listening...")
                        : t("已连接，您可以说话或打字", "Connected: speak or type freely")))
                : t("正在建立安全连接...", "Connecting live session...")}
            </span>
            {voiceChat.voiceChatConnected && (
              <span className="vsVoiceModelBadge">
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
            )}
          </div>

          <div className="vsVoiceVisualizerContainer" id="vs-voice-visualizer">
            <div className="vsVoiceVisualizerWave">
              <div className="vsWaveBar bar-1"></div>
              <div className="vsWaveBar bar-2"></div>
              <div className="vsWaveBar bar-3"></div>
              <div className="vsWaveBar bar-4"></div>
              <div className="vsWaveBar bar-5"></div>
              <div className="vsWaveBar bar-6"></div>
              <div className="vsWaveBar bar-7"></div>
            </div>
            <div className="vsVoiceGlow"></div>
          </div>

          <button
            type="button"
            className="vsVoiceCallHangupMiniBtn"
            onClick={() => void voiceChat.onToggleRecording()}
            title={t("挂断实时通话", "Hang up call")}
          >
            <StopIcon />
            <span>{t("挂断", "Hang up")}</span>
          </button>
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

          {/* Unified provider → model → voice picker */}
          <VoiceCallSettingsPopover
            voiceChat={voiceChat}
            chat={chat}
            t={t}
            disabled={isVoiceActive}
            onOpenSettings={onOpenSettings}
          />
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
              aria-label={t("实时通话", "Realtime call")}
              onClick={() => {
                if (!isRealtime) return;
                void voiceChat.onToggleRecording();
              }}
              disabled={!isRealtime || !voiceChat.voiceChatSupported || voiceChat.voiceChatBusy}
              title={
                !isRealtime
                  ? t(
                      "当前选择的是文本/多模态模型，实时通话请在左侧切换为实时语音模型（如带「实时」徽章的模型）",
                      "Current model is a text/multimodal model. Switch to a realtime voice model on the left to start a call."
                    )
                  : isLiveTranslate
                    ? t(`实时翻译：${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`, `Live translate: ${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`)
                    : t(`实时通话：${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`, `Realtime call: ${voiceChat.voiceChatProvider} / ${voiceChat.voiceChatModel}`)
              }
            >
              <PhoneIcon />
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
