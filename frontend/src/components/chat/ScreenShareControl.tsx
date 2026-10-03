import { useEffect, useRef } from "react";
import { Monitor, Square } from "lucide-react";
import type { UseVoiceChatResult } from "../../hooks/useVoiceChat";
import { useI18n } from "../../i18n";

export default function ScreenShareControl({ voiceChat }: { voiceChat: UseVoiceChatResult }) {
  const { t } = useI18n();
  const preview = useRef<HTMLVideoElement>(null);
  const capture = voiceChat.voiceChatScreenShare;
  useEffect(() => {
    const video = preview.current;
    if (!video || !capture?.stream) return;
    video.srcObject = capture.stream;
    void video.play().catch(() => {});
    return () => { video.srcObject = null; };
  }, [capture?.stream]);
  if (!capture) return null;
  if (voiceChat.voiceChatProvider === "Vercel" && voiceChat.voiceChatModel.startsWith("google/gemini-3.8-live")) {
    return <div className="vsComposerInlineHint">{t("Vercel 实时通话目前不支持屏幕输入。共享屏幕请选 Google Gemini API 或 Google Agent Platform。", "Vercel realtime currently does not accept screen input. Choose Google Gemini API or Google Agent Platform to share your screen.")}</div>;
  }
  if (!voiceChat.voiceChatScreenShareSupported) return null;
  const sourceLabel = /^(screen|window):/.test(capture.source)
    ? (capture.source.startsWith("screen:") ? t("整个屏幕", "Entire screen") : t("所选窗口", "Selected window"))
    : capture.source || t("所选画面", "Selected view");
  const title = capture.sharing
    ? t("正在向模型共享屏幕", "Sharing your screen with the model")
    : capture.pending ? t("选择要共享的画面", "Choose what to share") : t("让模型看到您的屏幕", "Let the model see your screen");
  return <div className={`vsScreenShareControl ${capture.sharing ? "is-sharing" : ""}`}>
    {capture.sharing && <video ref={preview} muted playsInline aria-label={t("共享屏幕预览", "Shared screen preview")} />}
    {!capture.sharing && <div className="vsScreenShareIcon" aria-hidden="true"><Monitor size={20} /></div>}
    <div className="vsScreenShareDescription">
      <span className="vsScreenShareTitle">
        {capture.sharing && <span className="vsScreenShareDot" aria-hidden="true" />}
        {title}
      </span>
      {capture.sharing ? <small title={sourceLabel}>{sourceLabel}</small> : capture.supported && <small>{t("选择屏幕或窗口，随时可以停止", "Choose a screen or window. Stop at any time.")}</small>}
      {!capture.supported && <small>{t("请使用 Chrome、Edge 或 Electron 桌面版", "Use Chrome, Edge, or the Electron desktop app")}</small>}
    </div>
    <button type="button" className="vsScreenShareButton" aria-pressed={capture.sharing}
      disabled={!capture.sharing && !capture.pending && (!voiceChat.voiceChatConnected || !capture.supported)}
      onClick={() => capture.sharing || capture.pending ? capture.stop() : void capture.start()}>
      {capture.sharing || capture.pending ? <Square size={15} /> : <Monitor size={15} />}
      {capture.sharing ? t("停止共享", "Stop sharing") : capture.pending ? t("取消共享", "Cancel sharing") : t("共享屏幕", "Share screen")}
    </button>
    {capture.error && <small className="vsScreenShareError" role="alert">{capture.error}</small>}
  </div>;
}
