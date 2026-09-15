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
  listTavusFaces,
  listTavusPals,
  persistTavusApiKey,
  persistTavusPalId,
  type TavusFaceSummary,
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
const MANUAL_FACE_VALUE = "__manual_face__";
const formatPhoenixModel = (model: string) => model.replace(/^phoenix-/i, "Phoenix ");

export function getRollingSubtitleText(text: string, latinMax = 120, cjkMax = 60): string {
  if (!text) return "";
  const hasCjk = /[\u4e00-\u9fff\u3040-\u30ff]/.test(text);
  const maxChars = hasCjk ? cjkMax : latinMax;
  if (text.length <= maxChars) {
    return text;
  }
  const rawTail = text.slice(-maxChars);
  const boundaryMatch = rawTail.search(/[.!?。！？，、;\n]\s*/);
  if (boundaryMatch >= 0 && boundaryMatch < maxChars * 0.45) {
    return `… ${rawTail.slice(boundaryMatch + 1).trimStart()}`;
  }
  const spaceIndex = rawTail.indexOf(" ");
  if (spaceIndex >= 0 && spaceIndex < 25) {
    return `… ${rawTail.slice(spaceIndex + 1).trimStart()}`;
  }
  return `… ${rawTail.trimStart()}`;
}

export default function PalPage({ formatErrorMessage, errorRuntimeContext }: Props) {
  const { t, language } = useI18n();
  const conversation = useTavusConversation({ formatErrorMessage, language });
  const [apiKey, setApiKey] = useState(() => getPersistedTavusApiKey());
  const [palIdInput, setPalIdInput] = useState(() => getPersistedTavusPalId());
  const [pals, setPals] = useState<TavusPalSummary[]>([]);
  const [selectedPalId, setSelectedPalId] = useState(MANUAL_PAL_VALUE);
  const [faces, setFaces] = useState<TavusFaceSummary[]>([]);
  const [selectedFaceId, setSelectedFaceId] = useState("");
  const [faceIdInput, setFaceIdInput] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const [showDrawer, setShowDrawer] = useState(false);
  const [copied, setCopied] = useState(false);
  const [summaryDismissed, setSummaryDismissed] = useState(false);

  useEffect(() => {
    let disposed = false;
    setPals([]);
    setFaces([]);
    setCatalogError("");
    setSelectedFaceId("");
    Promise.resolve(listTavusPals())
      .then((payload) => {
        if (disposed || !payload) {
          return;
        }
        setPals(payload.pals || []);
        if (payload.pals && payload.pals.length > 0) {
          const savedPalId = getPersistedTavusPalId();
          setSelectedPalId(savedPalId
            ? (payload.pals.some((pal) => pal.pal_id === savedPalId) ? savedPalId : MANUAL_PAL_VALUE)
            : payload.pals[0].pal_id);
        }
      })
      .catch((error) => {
        if (!disposed) setCatalogError(error instanceof Error ? error.message : String(error));
      });
    let facesDisposed = false;
    Promise.resolve(listTavusFaces())
      .then((payload) => {
        if (facesDisposed || !payload) {
          return;
        }
        setFaces([...(payload.faces || [])].sort((a, b) =>
          Number(b.model_name === "phoenix-4.5") - Number(a.model_name === "phoenix-4.5")));
      })
      .catch((error) => {
        if (!facesDisposed) setCatalogError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      disposed = true;
      facesDisposed = true;
    };
  }, [apiKey]);

  const resolvedPalId = useMemo(() => {
    if (pals.length > 0 && selectedPalId !== MANUAL_PAL_VALUE) {
      return selectedPalId;
    }
    return palIdInput.trim();
  }, [palIdInput, pals.length, selectedPalId]);

  const resolvedFaceId = useMemo(() => {
    if (selectedFaceId === MANUAL_FACE_VALUE) {
      return faceIdInput.trim();
    }
    return selectedFaceId;
  }, [faceIdInput, selectedFaceId]);

  const faceGroups = useMemo(() => {
    const groups = new Map<string, TavusFaceSummary[]>();
    for (const face of faces) {
      const model = face.model_name || "";
      groups.set(model, [...(groups.get(model) || []), face]);
    }
    return [...groups.entries()].sort(([a], [b]) => b.localeCompare(a, undefined, { numeric: true }));
  }, [faces]);
  const selectedPal = pals.find((pal) => pal.pal_id === resolvedPalId);
  const effectiveFaceId = resolvedFaceId || selectedPal?.default_face_id;
  const effectiveFace = faces.find((face) => face.face_id === effectiveFaceId);
  const faceUnavailable = Boolean(effectiveFace?.status && effectiveFace.status !== "completed");

  const showConfigPanel =
    conversation.status === "idle" ||
    (conversation.status === "ended" && (conversation.transcripts.length === 0 || summaryDismissed));
  const showPostCallSummary =
    conversation.status === "ended" && conversation.transcripts.length > 0 && !summaryDismissed;
  const isPending = conversation.status === "creating" || conversation.status === "joining";

  useEffect(() => {
    if (!showPostCallSummary) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSummaryDismissed(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showPostCallSummary]);

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
    setSummaryDismissed(false);
    setShowDrawer(false);
    conversation.clearTranscripts();
    void conversation.start({
      palId: resolvedPalId || undefined,
      palName: selectedPal?.pal_name || undefined,
      faceId: resolvedFaceId || undefined,
    });
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
                  <p>{t("PAL 决定角色与对话方式；Face 决定视频形象及 Phoenix 渲染版本。", "PAL sets the role and conversation behavior; Face sets the appearance and Phoenix rendering version.")}</p>
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
                  <span>{t("选择角色（PAL）", "Choose a role (PAL)")}</span>
                  <select
                    value={selectedPalId}
                    onChange={(event) => {
                      setSelectedPalId(event.target.value);
                      if (event.target.value !== MANUAL_PAL_VALUE) {
                        handlePalIdInputChange(event.target.value);
                      }
                    }}
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

              {catalogError ? <p role="alert">{t("无法加载分身或形象列表：", "Could not load PALs or faces: ")}{catalogError}</p> : null}

              <label className="vsPalField">
                <span>
                  {t("选择视频形象（Face）与模型", "Choose a video face and model")}
                </span>
                <select
                  value={selectedFaceId}
                  onChange={(event) => setSelectedFaceId(event.target.value)}
                  data-testid="pal-face-select"
                >
                  <option value="">{t("使用分身默认形象", "Use the PAL's default face")}</option>
                  {faceGroups.map(([model, group]) => (
                    <optgroup key={model} label={`${model ? formatPhoenixModel(model) : t("模型未知", "Unknown model")} · ${group.length}`}>
                    {group.map((face) => (
                    <option key={face.face_id} value={face.face_id} disabled={Boolean(face.status && face.status !== "completed")}>
                      {face.face_name}
                      {face.model_name
                        ? ` · ${formatPhoenixModel(face.model_name)}`
                        : ""}
                      {face.status && face.status !== "completed" ? ` (${face.status})` : ""}
                    </option>
                    ))}
                    </optgroup>
                  ))}
                  <option value={MANUAL_FACE_VALUE}>{t("手动输入 Face ID...", "Enter a Face ID...")}</option>
                </select>
                <small>
                  {t(
                    "分身自带默认绑定的形象与版本。仅在想临时覆盖使用其他形象（如体验 Phoenix 4.5 高清效果）时切换。",
                    "The PAL uses its assigned default face by default. Change this only if you want to override it (e.g. to try a Phoenix 4.5 face)."
                  )}
                </small>
              </label>

              <div className="vsPalField" data-testid="pal-effective-face" role="status">
                <span>{t("本次使用", "This conversation uses")}</span>
                <small>{effectiveFace
                  ? `${effectiveFace.face_name} · ${effectiveFace.model_name ? formatPhoenixModel(effectiveFace.model_name) : t("模型未知", "Unknown model")}`
                  : t("模型尚未确认，请选择有模型标签的形象。默认或手动 ID 不保证使用 Phoenix 4.5。", "Model not confirmed. Choose a face with a model label. Default or manual IDs do not guarantee Phoenix 4.5.")}</small>
                {faceUnavailable ? <small>{t("该形象尚未就绪，请选择其他形象。", "This face is not ready. Choose another face.")}</small> : null}
              </div>

              {selectedFaceId === MANUAL_FACE_VALUE ? (
                <label className="vsPalField">
                  <span>{t("Face ID (数字人形象 ID)", "Face ID (Avatar Face ID)")}</span>
                  <input
                    value={faceIdInput}
                    onChange={(event) => setFaceIdInput(event.target.value)}
                    placeholder={t("在 PAL Maker 创建的形象 ID (如 rc9cff...)", "Face ID from PAL Maker (e.g. rc9cff...)")}
                    data-testid="pal-face-id-input"
                  />
                </label>
              ) : null}

              <button
                type="submit"
                className="vsPalStartBtn"
                disabled={isPending || faceUnavailable}
                data-testid="pal-start-button"
              >
                <Play size={16} />
                <span>{t("开始视频对话", "Start video conversation")}</span>
              </button>
            </form>
          </div>
        ) : null}

        {showPostCallSummary ? (
          <div
            className="vsPalOverlay"
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setSummaryDismissed(true);
              }
            }}
          >
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
                    className="vsPalGhostBtn"
                    onClick={() => setSummaryDismissed(true)}
                    data-testid="pal-dismiss-summary-button"
                  >
                    <span>{t("返回配置", "Back to Setup")}</span>
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
                  <button
                    type="button"
                    className="vsPalCloseBtn"
                    onClick={() => setSummaryDismissed(true)}
                    title={t("关闭 (Esc)", "Close (Esc)")}
                    aria-label={t("关闭", "Close")}
                    data-testid="pal-close-summary-button"
                  >
                    <X size={18} strokeWidth={2.25} />
                  </button>
                </div>
              </div>

              <div className="vsPalTranscriptScrollArea">
                {conversation.transcripts.map((item) => (
                  <div key={item.id} className={`vsPalTranscriptRow ${item.speaker}`}>
                    <div className="vsPalTranscriptMeta">
                      <span className="vsPalTranscriptName">{item.speakerName}</span>
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
                <span className="vsPalSubSpeaker">{conversation.activeSubtitle.speakerName}:</span>
                <span className="vsPalSubText">{getRollingSubtitleText(conversation.activeSubtitle.text)}</span>
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
