import { useState } from "react";

import { useLocalVoiceStatus } from "../../hooks/useLocalVoiceStatus";
import type { LocalVoiceProviderState, UseLocalVoiceStatusResult } from "../../hooks/useLocalVoiceStatus";
import { useI18n } from "../../i18n";

// HF tokens are only needed to download the gated PersonaPlex weights; keep
// them in localStorage (not config.json) so they never touch synced settings.
const HF_TOKEN_STORAGE_KEY = "echo.hfAccessToken";

type ProviderMeta = {
  key: string;
  name: string;
  descZh: string;
  descEn: string;
  needsHfToken: boolean;
};

const LOCAL_PROVIDERS: ProviderMeta[] = [
  {
    key: "GLM4Voice",
    name: "GLM-4-Voice 9B",
    descZh: "智谱开源端到端语音对话模型，中英文双语，本地全双工实时通话。",
    descEn: "Zhipu's open-source end-to-end speech model; bilingual, fully local duplex calls.",
    needsHfToken: false,
  },
  {
    key: "PersonaPlex",
    name: "PersonaPlex 7B",
    descZh: "NVIDIA 全双工语音模型，支持角色人设与多种音色。权重托管在 HuggingFace 受限仓库。",
    descEn: "NVIDIA's duplex voice model with personas and multiple voices. Weights are in a gated HuggingFace repo.",
    needsHfToken: true,
  },
];

function ProviderCard({ meta, state, voice }: {
  meta: ProviderMeta;
  state: LocalVoiceProviderState | undefined;
  voice: UseLocalVoiceStatusResult;
}) {
  const { t } = useI18n();
  const [hfToken, setHfToken] = useState(() => localStorage.getItem(HF_TOKEN_STORAGE_KEY) || "");

  const status = state?.status;
  const phase = state?.phase ?? "not-installed";
  const gpu = status?.gpu;
  const gpuTooSmall =
    gpu?.available && status ? (gpu.vram_gb ?? 0) < status.requirements.min_vram_gb : false;
  const diskTooSmall =
    status ? status.disk_free_gb < status.requirements.approx_download_gb + 2 : false;

  const phaseLabel = (() => {
    switch (phase) {
      case "running": return { text: t("● 运行中", "● Running"), cls: "local-running" };
      case "starting": return { text: t("⏳ 启动中…", "⏳ Starting…"), cls: "local-installing" };
      case "installing": return { text: t("⏳ 安装中", "⏳ Installing"), cls: "local-installing" };
      case "installed": return { text: t("▶ 已就绪，待启动", "▶ Ready to start"), cls: "local-ready" };
      default: return { text: t("⬇ 未安装", "⬇ Not installed"), cls: "local-missing" };
    }
  })();

  const saveToken = (value: string) => {
    setHfToken(value);
    localStorage.setItem(HF_TOKEN_STORAGE_KEY, value);
  };

  return (
    <div className="vsCardSection border-top">
      <h3 className="vsCardSubTitle" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {meta.name}
        <span className={`vsProviderBadge ${phaseLabel.cls}`}>{phaseLabel.text}</span>
      </h3>
      <p className="vsFieldHint" style={{ marginTop: 0 }}>{t(meta.descZh, meta.descEn)}</p>

      {status && (
        <div className="vsFormRow">
          <label className="vsField">
            <span className="vsFieldLabel">{t("硬件要求", "Requirements")}</span>
            <input
              className="vsInput"
              readOnly
              value={t(
                `显存 ≥ ${status.requirements.min_vram_gb} GB ｜ 下载约 ${status.requirements.approx_download_gb.toFixed(0)} GB`,
                `VRAM ≥ ${status.requirements.min_vram_gb} GB | ~${status.requirements.approx_download_gb.toFixed(0)} GB download`
              )}
            />
          </label>
          <label className="vsField">
            <span className="vsFieldLabel">{t("检测到的 GPU", "Detected GPU")}</span>
            <input
              className="vsInput"
              readOnly
              value={
                gpu?.available
                  ? `${gpu.name} (${gpu.vram_gb} GB)`
                  : t("未检测到 NVIDIA GPU", "No NVIDIA GPU detected")
              }
            />
          </label>
        </div>
      )}

      {gpu && !gpu.available && (
        <div className="vsSettingsNotice warning">
          ⚠️ {t(
            "未检测到 NVIDIA GPU。本地语音模型需要 CUDA 显卡，当前设备可能无法运行。",
            "No NVIDIA GPU detected. Local voice models need a CUDA-capable GPU."
          )}
        </div>
      )}
      {gpuTooSmall && status && (
        <div className="vsSettingsNotice warning">
          ⚠️ {t(
            `显存不足：检测到 ${gpu?.vram_gb} GB，该模型建议 ≥ ${status.requirements.min_vram_gb} GB。`,
            `Insufficient VRAM: ${gpu?.vram_gb} GB detected, ≥ ${status.requirements.min_vram_gb} GB recommended.`
          )}
        </div>
      )}
      {diskTooSmall && status && phase === "not-installed" && (
        <div className="vsSettingsNotice warning">
          ⚠️ {t(
            `磁盘空间不足：剩余 ${status.disk_free_gb} GB，安装需要约 ${(status.requirements.approx_download_gb + 2).toFixed(0)} GB。`,
            `Low disk space: ${status.disk_free_gb} GB free, ~${(status.requirements.approx_download_gb + 2).toFixed(0)} GB needed.`
          )}
        </div>
      )}

      {meta.needsHfToken && ["not-installed", "installed", "error"].includes(phase) && (
        <div className="vsFormRow">
          <label className="vsField" style={{ flex: 1 }}>
            <span className="vsFieldLabel">HuggingFace Access Token</span>
            <input
              className="vsInput"
              type="password"
              value={hfToken}
              onChange={(e) => saveToken(e.target.value)}
              placeholder="hf_..."
            />
            <span className="vsFieldHint">
              {t(
                "先在 huggingface.co 接受 nvidia/personaplex-7b-v1 的许可协议，再在此粘贴 Access Token（仅保存在本机浏览器）。",
                "Accept the nvidia/personaplex-7b-v1 license on huggingface.co, then paste your access token (stored only in this browser)."
              )}
            </span>
          </label>
        </div>
      )}

      {phase === "installing" && state?.setupJob && (
        <div className="vsSettingsNotice" style={{ padding: "10px 14px" }}>
          <div style={{ marginBottom: 6, fontSize: 13 }}>
            {state.setupJob.message || t("安装中…", "Installing…")}
            {" — "}{(state.setupJob.percent ?? 0).toFixed(0)}%
          </div>
          <div style={{ height: 6, borderRadius: 3, background: "var(--border, rgba(255,255,255,0.1))", overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${state.setupJob.percent ?? 0}%`,
                background: "var(--accent, #6ee7b7)",
                transition: "width 0.3s ease",
                borderRadius: 3,
              }}
            />
          </div>
        </div>
      )}

      {state?.error && (
        <div className="vsSettingsNotice warning">⚠️ {state.error}</div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        {phase === "not-installed" && (
          <button
            type="button"
            className="vsBtnPrimary"
            disabled={diskTooSmall}
            onClick={() => voice.setup(meta.key, hfToken)}
          >
            {t("一键安装", "Install")}
          </button>
        )}
        {phase === "error" && (
          <button
            type="button"
            className="vsBtnPrimary"
            onClick={() => voice.setup(meta.key, hfToken)}
          >
            {t("重试安装", "Retry install")}
          </button>
        )}
        {phase === "installing" && (
          <button type="button" className="vsBtnSecondary" onClick={() => voice.cancelSetup(meta.key)}>
            {t("取消安装", "Cancel")}
          </button>
        )}
        {phase === "installed" && (
          <button type="button" className="vsBtnPrimary" onClick={() => voice.startServer(meta.key, hfToken)}>
            {t("启动服务", "Start server")}
          </button>
        )}
        {phase === "starting" && (
          <button type="button" className="vsBtnPrimary" disabled>
            {t("启动中…", "Starting…")}
          </button>
        )}
        {phase === "running" && (
          <button type="button" className="vsBtnSecondary" onClick={() => voice.stopServer(meta.key)}>
            {t("停止服务", "Stop server")}
          </button>
        )}
      </div>
    </div>
  );
}

export default function LocalVoiceSettingsSection() {
  const { t } = useI18n();
  const voice = useLocalVoiceStatus(true);

  return (
    <div className="vsSettingsCard">
      <div className="vsCardSection">
        <h3 className="vsCardSubTitle">{t("本地语音模型", "Local Voice Models")}</h3>
        <p className="vsFieldHint" style={{ marginTop: 0 }}>
          {t(
            "无需任何云端 API Key，完全在本机运行的全双工实时语音模型。首次安装会下载运行时与模型权重，之后可离线使用。",
            "Fully local duplex voice models — no cloud API key needed. The first install downloads the runtime and weights; afterwards they work offline."
          )}
        </p>
      </div>
      {LOCAL_PROVIDERS.map((meta) => (
        <ProviderCard key={meta.key} meta={meta} state={voice.providers[meta.key]} voice={voice} />
      ))}
    </div>
  );
}
