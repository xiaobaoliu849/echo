import { useEffect, useMemo, useState } from "react";
import { KeyRound, LogOut, Mic, MicOff, Play, Video, VideoOff } from "lucide-react";
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

  const showConfigPanel = conversation.status === "idle" || conversation.status === "ended";
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
    void conversation.start({ palId: resolvedPalId || undefined });
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
          <div className="vsPalLiveBar">
            <span className="vsPalLiveDot" aria-hidden="true" />
            <span>{t("通话中", "Live")}</span>

            <div
              className="vsPalAudioMeter"
              title={
                conversation.isMuted
                  ? t("麦克风已静音 (点击开启)", "Microphone muted (click to unmute)")
                  : t("麦克风拾音中 (说话时右侧绿条会跳动)", "Microphone active (green bar pulses when speaking)")
              }
            >
              <button
                type="button"
                className={`vsPalControlBtn ${conversation.isMuted ? "isMuted" : ""}`}
                onClick={conversation.toggleMute}
                title={conversation.isMuted ? t("取消静音", "Unmute microphone") : t("静音麦克风", "Mute microphone")}
                data-testid="pal-toggle-mute-button"
              >
                {conversation.isMuted ? <MicOff size={14} /> : <Mic size={14} />}
              </button>
              <div className="vsPalLevelBarTrack">
                <div
                  className={`vsPalLevelBarFill ${conversation.localAudioLevel > 0.04 ? "speaking" : ""}`}
                  style={{
                    width: conversation.isMuted
                      ? "0%"
                      : `${Math.min(100, Math.round(conversation.localAudioLevel * 250))}%`,
                  }}
                />
              </div>
            </div>

            <button
              type="button"
              className={`vsPalControlBtn ${conversation.isVideoOff ? "isMuted" : ""}`}
              onClick={conversation.toggleVideo}
              title={conversation.isVideoOff ? t("打开摄像头", "Turn on camera") : t("关闭摄像头", "Turn off camera")}
              data-testid="pal-toggle-video-button"
            >
              {conversation.isVideoOff ? <VideoOff size={14} /> : <Video size={14} />}
            </button>

            <button
              type="button"
              className="vsPalLeaveBtn"
              onClick={conversation.leave}
              data-testid="pal-leave-button"
            >
              <LogOut size={15} />
              <span>{t("结束通话", "Leave")}</span>
            </button>
          </div>
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
