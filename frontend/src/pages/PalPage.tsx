import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Copy,
  KeyRound,
  MessageSquareText,
  Mic,
  MicOff,
  Monitor,
  MonitorOff,
  PhoneOff,
  Play,
  RotateCcw,
  Subtitles,
  Video,
  VideoOff,
  X,
} from "lucide-react";
import ErrorNotice from "../components/ErrorNotice";
import useTavusConversation from "../hooks/useTavusConversation";
import {
  getPersistedTavusApiKey,
  getPersistedTavusPalId,
  listTavusPals,
  persistTavusApiKey,
  persistTavusPalId,
  type TavusPalSummary,
} from "../api";
import { useI18n } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import type { ErrorRuntimeContext } from "../types/ui";

type Props = {
  formatErrorMessage: FormatErrorMessage;
  errorRuntimeContext: ErrorRuntimeContext;
};

const MANUAL_PAL_VALUE = "__manual__";

export default function PalPage({ formatErrorMessage, errorRuntimeContext }: Props) {
  const { t, language } = useI18n();
  const conversation = useTavusConversation({ formatErrorMessage, language });
  const [apiKey, setApiKey] = useState(() => getPersistedTavusApiKey());
  const [palIdInput, setPalIdInput] = useState(() => getPersistedTavusPalId());
  const [pals, setPals] = useState<TavusPalSummary[]>([]);
  const [selectedPalId, setSelectedPalId] = useState(MANUAL_PAL_VALUE);
  const [showDrawer, setShowDrawer] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let disposed = false;
    Promise.resolve(listTavusPals())
      .then((payload) => {
        if (disposed || !payload) {
          return;
        }
        setPals(payload.pals || []);
        if (payload.pals && payload.pals.length > 0) {
          setSelectedPalId(payload.pals[0].pal_id);
        }
      })
      .catch(() => {
        // Falls back to manual PAL entry; the start attempt surfaces real errors.
      });
    return () => {
      disposed = true;
    };
  }, [apiKey]);

  const resolvedPalId = useMemo(() => {
    if (pals.length > 0 && selectedPalId !== MANUAL_PAL_VALUE) {
      return selectedPalId;
    }
    return palIdInput.trim();
  }, [palIdInput, pals.length, selectedPalId]);

  const showConfigPanel = conversation.status === "idle" || (conversation.status === "ended" && conversation.transcripts.length === 0);
  const showPostCallSummary = conversation.status === "ended" && conversation.transcripts.length > 0;
  const isPending = conversation.status === "creating" || conversation.status === "joining";

  const pendingLabel = conversation.status === "creating"
    ? t("正在创建视频会话...", "Creating the video conversation...")
    : t("正在接入视频房间...", "Joining the video room...");

  function handleApiKeyChange(value: string) {
    setApiKey(value);
    persistTavusApiKey(value);
  }

  function handlePalIdInputChange(value: string) {
    setPalIdInput(value);
    persistTavusPalId(value);
  }

  function handleStart() {
    setShowDrawer(false);
    conversation.clearTranscripts();
    void conversation.start({ palId: resolvedPalId || undefined });
  }

  function handleCopyTranscript() {
    const fullText = conversation.transcripts
      .map((item) => `[${new Date(item.timestamp).toLocaleTimeString()}] ${item.speakerName}: ${item.text}`)
      .join("\n\n");
    if (!fullText) return;
    navigator.clipboard.writeText(fullText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <section className="vsPalPage">
      <div className="vsPalStage">
        <div ref={conversation.attachVideoContainer} className="vsPalVideoHost" data-testid="pal-video-host" />

        {showConfigPanel ? (
          <div className="vsPalOverlay">
            <form
              className="vsPalConfigCard"
              onSubmit={(event) => {
                event.preventDefault();
                handleStart();
              }}
            >
              <div className="vsPalConfigHead">
                <span className="vsPalConfigIcon" aria-hidden="true">
                  <Video size={22} />
                </span>
                <div>
                  <h2>{t("AI 视频分身", "AI Video PAL")}</h2>
                  <p>{t("与你的 Tavus 分身进行实时视频对话。", "Have a realtime video conversation with your Tavus PAL.")}</p>
                </div>
              </div>

              {conversation.status === "ended" ? (
                <p className="vsPalEndedHint">{t("上一场通话已结束。", "The previous conversation has ended.")}</p>
              ) : null}

              <label className="vsPalField">
                <span>{t("Tavus API Key", "Tavus API Key")}</span>
                <div className="vsPalKeyRow">
                  <span className="vsPalKeyIcon" aria-hidden="true">
                    <KeyRound size={15} />
                  </span>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(event) => handleApiKeyChange(event.target.value)}
                    placeholder={t("粘贴 API Key（仅保存在本机）", "Paste your API key (stored locally only)")}
                    autoComplete="off"
                    data-testid="pal-api-key-input"
                  />
                </div>
                <small>
                  {t(
                    "在 platform.tavus.io 创建，仅在本机与后端之间传输。",
                    "Create one at platform.tavus.io. It only travels between this machine and the backend."
                  )}
                </small>
              </label>

              {pals.length > 0 ? (
                <label className="vsPalField">
                  <span>{t("选择分身", "Choose a PAL")}</span>
                  <select
                    value={selectedPalId}
                    onChange={(event) => setSelectedPalId(event.target.value)}
                    data-testid="pal-select"
                  >
                    {pals.map((pal) => (
                      <option key={pal.pal_id} value={pal.pal_id}>
                        {pal.pal_name}
                      </option>
                    ))}
                    <option value={MANUAL_PAL_VALUE}>{t("手动输入 PAL ID...", "Enter a PAL ID...")}</option>
                  </select>
                </label>
              ) : null}

              {pals.length === 0 || selectedPalId === MANUAL_PAL_VALUE ? (
                <label className="vsPalField">
                  <span>{t("PAL ID (数字人分身 ID)", "PAL ID (Avatar Persona ID)")}</span>
                  <input
                    value={palIdInput}
                    onChange={(event) => handlePalIdInputChange(event.target.value)}
                    placeholder={t("在 platform.tavus.io 创建的 PAL ID (如 p9a8d...)", "PAL ID from platform.tavus.io (e.g. p9a8d...)")}
                    data-testid="pal-id-input"
                  />
                  <small>
                    {t(
                      "在 platform.tavus.io 创建分身后会自动列在下拉列表中，也可在此手动粘贴 PAL ID。",
                      "Personas created on platform.tavus.io appear in the dropdown, or you can paste a PAL ID manually here."
                    )}
                  </small>
                </label>
              ) : null}

              <button
                type="submit"
                className="vsPalStartBtn"
                disabled={isPending}
                data-testid="pal-start-button"
              >
                <Play size={16} />
                <span>{t("开始视频对话", "Start video conversation")}</span>
              </button>
            </form>
          </div>
        ) : null}

        {showPostCallSummary ? (
          <div className="vsPalOverlay">
            <div className="vsPalSummaryCard">
              <div className="vsPalSummaryHead">
                <div>
                  <h2>{t("通话已结束", "Call Ended")}</h2>
                  <p>{t("通话时长", "Duration")}: <strong>{conversation.formattedDuration}</strong> · {t("对话条数", "Messages")}: <strong>{conversation.transcripts.length}</strong></p>
                </div>
                <div className="vsPalSummaryActions">
                  <button
                    type="button"
                    className="vsPalGhostBtn"
                    onClick={handleCopyTranscript}
                    title={t("复制对话全文", "Copy full transcript")}
                  >
                    {copied ? <Check size={15} color="#10b981" /> : <Copy size={15} />}
                    <span>{copied ? t("已复制", "Copied") : t("复制记录", "Copy")}</span>
                  </button>
                  <button
                    type="button"
                    className="vsPalRestartBtn"
                    onClick={handleStart}
                    data-testid="pal-start-button"
                  >
                    <RotateCcw size={15} />
                    <span>{t("再次通话", "Call Again")}</span>
                  </button>
                </div>
              </div>

              <div className="vsPalTranscriptScrollArea">
                {conversation.transcripts.map((item) => (
                  <div key={item.id} className={`vsPalTranscriptRow ${item.speaker}`}>
                    <div className="vsPalTranscriptMeta">
                      <span className="vsPalTranscriptName">{item.speaker === "user" ? "🗣️" : "🤖"} {item.speakerName}</span>
                      <span className="vsPalTranscriptTime">{new Date(item.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                    </div>
                    <div className="vsPalTranscriptBubble">{item.text}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {conversation.status === "creating" ? (
          <div className="vsPalOverlay">
            <div className="vsPalPendingCard" role="status">
              <span className="vsPalSpinner" aria-hidden="true" />
              <span>{pendingLabel}</span>
            </div>
          </div>
        ) : null}

        {conversation.status === "joining" ? (
          <div className="vsPalPendingPill" role="status">
            <span className="vsPalSpinner" aria-hidden="true" />
            <span>{pendingLabel}</span>
          </div>
        ) : null}

        {conversation.status === "connected" ? (
          <>
            {/* Minimalist Top Status Pill */}
            <div className="vsPalHeaderBadge" role="status">
              <span className="vsPalLiveDot" aria-hidden="true" />
              <span className="vsPalDuration">{conversation.formattedDuration}</span>
              <span className="vsPalBadgeDivider">·</span>
              <span className="vsPalStatusText">{t("通话中", "Live")}</span>
            </div>

            {/* Live Floating Subtitle Banner */}
            {conversation.showSubtitles && conversation.activeSubtitle ? (
              <div className={`vsPalFloatingSubtitle ${conversation.activeSubtitle.speaker}`} role="status">
                <span className="vsPalSubSpeaker">
                  {conversation.activeSubtitle.speaker === "user" ? "🗣️ " : "🤖 "}
                  {conversation.activeSubtitle.speakerName}
                </span>
                <span className="vsPalSubText">{conversation.activeSubtitle.text}</span>
              </div>
            ) : null}

            {/* Side Transcript Drawer */}
            {showDrawer ? (
              <aside className="vsPalTranscriptDrawer" aria-label={t("实时对话记录", "Live conversation transcript")}>
                <div className="vsPalDrawerHead">
                  <h3>{t("实时速记", "Live Transcript")} ({conversation.transcripts.length})</h3>
                  <div className="vsPalDrawerActions">
                    <button
                      type="button"
                      className="vsPalDrawerIconBtn"
                      onClick={handleCopyTranscript}
                      title={t("复制对话全文", "Copy full transcript")}
                    >
                      {copied ? <Check size={15} color="#10b981" /> : <Copy size={15} />}
                    </button>
                    <button
                      type="button"
                      className="vsPalDrawerIconBtn"
                      onClick={() => setShowDrawer(false)}
                      title={t("关闭速记", "Close drawer")}
                    >
                      <X size={15} />
                    </button>
                  </div>
                </div>

                <div className="vsPalDrawerBody">
                  {conversation.transcripts.length === 0 ? (
                    <div className="vsPalDrawerEmpty">{t("对话开始后，发言将实时显示在此...", "Speech will appear here in realtime...")}</div>
                  ) : (
                    conversation.transcripts.map((item) => (
                      <div key={item.id} className={`vsPalTranscriptRow ${item.speaker}`}>
                        <div className="vsPalTranscriptMeta">
                          <span className="vsPalTranscriptName">{item.speaker === "user" ? "🗣️" : "🤖"} {item.speakerName}</span>
                          <span className="vsPalTranscriptTime">{new Date(item.timestamp).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" })}</span>
                        </div>
                        <div className="vsPalTranscriptBubble">{item.text}</div>
                      </div>
                    ))
                  )}
                </div>
              </aside>
            ) : null}

            {/* Unified Bottom Floating Dock */}
            <div className="vsPalControlDock" role="toolbar" aria-label={t("通话控制", "Call controls")}>
              <button
                type="button"
                className={`vsPalDockBtn ${conversation.isMuted ? "isMuted" : ""}`}
                onClick={conversation.toggleMute}
                title={conversation.isMuted ? t("取消静音麦克风", "Unmute microphone") : t("静音麦克风", "Mute microphone")}
                data-testid="pal-toggle-mute-button"
                aria-label={conversation.isMuted ? t("取消静音", "Unmute") : t("静音", "Mute")}
              >
                {conversation.isMuted ? <MicOff size={18} /> : <Mic size={18} />}
                {!conversation.isMuted && conversation.localAudioLevel > 0.03 && (
                  <span
                    className="vsPalDockAudioHalo"
                    style={{
                      transform: `scale(${1 + Math.min(0.4, conversation.localAudioLevel * 2.5)})`,
                      opacity: Math.min(0.8, conversation.localAudioLevel * 4),
                    }}
                  />
                )}
              </button>

              <button
                type="button"
                className={`vsPalDockBtn ${conversation.isVideoOff ? "isMuted" : ""}`}
                onClick={conversation.toggleVideo}
                title={conversation.isVideoOff ? t("开启摄像头", "Turn on camera") : t("关闭摄像头", "Turn off camera")}
                data-testid="pal-toggle-video-button"
                aria-label={conversation.isVideoOff ? t("开启摄像头", "Turn on camera") : t("关闭摄像头", "Turn off camera")}
              >
                {conversation.isVideoOff ? <VideoOff size={18} /> : <Video size={18} />}
              </button>

              <button
                type="button"
                className={`vsPalDockBtn ${conversation.isSharingScreen ? "isActive" : ""}`}
                onClick={() => void conversation.toggleScreenShare()}
                title={conversation.isSharingScreen ? t("停止共享屏幕", "Stop screen sharing") : t("共享屏幕", "Share screen")}
                data-testid="pal-toggle-screen-button"
                aria-label={conversation.isSharingScreen ? t("停止共享", "Stop sharing") : t("共享屏幕", "Share screen")}
              >
                {conversation.isSharingScreen ? <MonitorOff size={18} /> : <Monitor size={18} />}
              </button>

              <button
                type="button"
                className={`vsPalDockBtn ${conversation.showSubtitles ? "isActive" : ""}`}
                onClick={conversation.toggleSubtitles}
                title={conversation.showSubtitles ? t("隐藏实时字幕", "Hide subtitles") : t("开启实时字幕", "Show subtitles")}
                data-testid="pal-toggle-subtitles-button"
                aria-label={conversation.showSubtitles ? t("隐藏字幕", "Hide subtitles") : t("开启字幕", "Show subtitles")}
              >
                <Subtitles size={18} />
              </button>

              <button
                type="button"
                className={`vsPalDockBtn ${showDrawer ? "isActive" : ""}`}
                onClick={() => setShowDrawer((prev) => !prev)}
                title={showDrawer ? t("收起速记面板", "Close transcript panel") : t("展开对话速记", "Open transcript panel")}
                data-testid="pal-toggle-drawer-button"
                aria-label={showDrawer ? t("收起速记", "Close transcript") : t("展开速记", "Open transcript")}
              >
                <MessageSquareText size={18} />
                {conversation.transcripts.length > 0 && (
                  <span className="vsPalDockCountBadge">{conversation.transcripts.length}</span>
                )}
              </button>

              <div className="vsPalDockDivider" aria-hidden="true" />

              <button
                type="button"
                className="vsPalHangupBtn"
                onClick={conversation.leave}
                title={t("结束通话", "End call")}
                data-testid="pal-leave-button"
                aria-label={t("结束通话", "End call")}
              >
                <PhoneOff size={18} />
                <span>{t("结束通话", "End Call")}</span>
              </button>
            </div>
          </>
        ) : null}
      </div>

      <ErrorNotice
        message={conversation.errorMessage}
        scope="pal"
        context={{
          ...errorRuntimeContext,
          pal_id: resolvedPalId || null
        }}
      />
    </section>
  );
}
