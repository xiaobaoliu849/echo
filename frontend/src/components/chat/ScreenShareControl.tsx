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
  return <div className="vsScreenShareControl">
    {capture.sharing && <video ref={preview} muted playsInline aria-label={t("共享屏幕预览", "Shared screen preview")} />}
    <div className="vsScreenShareDescription">
      <span>{capture.sharing ? t("正在向模型共享屏幕", "Sharing your screen with the model") : t("让模型看到您所选的屏幕或窗口", "Let the model see a screen or window you choose")}</span>
      {capture.sharing && <small title={capture.source}>{capture.source}</small>}
      {!capture.supported && <small>{t("请使用 Chrome、Edge 或 Electron 桌面版", "Use Chrome, Edge, or the Electron desktop app")}</small>}
      {capture.error && <small role="alert">{capture.error}</small>}
    </div>
    <button type="button" className="vsVoiceCallMuteBtn" aria-pressed={capture.sharing}
      disabled={!capture.sharing && !capture.pending && (!voiceChat.voiceChatConnected || !capture.supported)}
      onClick={() => capture.sharing || capture.pending ? capture.stop() : void capture.start()}>
      {capture.sharing || capture.pending ? <Square size={15} /> : <Monitor size={15} />}
      {capture.sharing ? t("停止共享", "Stop sharing") : capture.pending ? t("取消共享", "Cancel sharing") : t("共享屏幕", "Share screen")}
    </button>
  </div>;
}
