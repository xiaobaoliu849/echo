import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSpeakAudio, type CustomVoice } from "../api";
import { useI18n } from "../i18n";

type Props = {
  item: CustomVoice;
  onDelete: (e: React.MouseEvent) => void;
};

const PREVIEW_TEXT_ZH = "你好，这是 Echo 的音色试听，很高兴为你服务。";
const PREVIEW_TEXT_EN = "Hello, this is an Echo voice preview. Nice to meet you.";

/* Deterministic gradient palette based on string hash */
const COVER_GRADIENTS = [
  ["#f43f5e", "#fb7185", "#fda4af"], // rose
  ["#8b5cf6", "#a78bfa", "#c4b5fd"], // violet
  ["#3b82f6", "#60a5fa", "#93c5fd"], // blue
  ["#10b981", "#34d399", "#6ee7b7"], // emerald
  ["#f59e0b", "#fbbf24", "#fcd34d"], // amber
  ["#0ea5e9", "#38bdf8", "#7dd3fc"], // sky
];

function hashStr(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function DiamondPattern({ color }: { color: string }) {
  return (
    <svg className="vsTranscribeCardWave" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polygon points="50,0 100,50 50,100 0,50" fill={color} opacity="0.15" />
      <polygon points="10,20 30,40 10,60 -10,40" fill={color} opacity="0.2" />
      <polygon points="90,60 110,80 90,100 70,80" fill={color} opacity="0.2" />
    </svg>
  );
}

export const VoiceCard: React.FC<Props> = ({ item, onDelete }) => {
  const { t, language } = useI18n();
  const hash = useMemo(() => hashStr(item.voice), [item.voice]);
  const palette = COVER_GRADIENTS[hash % COVER_GRADIENTS.length];
  const isDesign = item.type === "voice_design";
  const providerLabel = item.provider ? ({
    qwen: "Qwen", gemini: "Gemini", elevenlabs: "ElevenLabs", gpt_sovits: "GPT-SoVITS",
  } as Record<string, string>)[item.provider] || item.provider : "";

  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    return () => {
      if (previewUrl.startsWith("blob:")) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  async function handlePreview() {
    if (previewLoading) return;
    if (previewUrl) {
      const audio = audioRef.current;
      if (!audio) return;
      if (audio.paused) {
        void audio.play();
      } else {
        audio.pause();
      }
      return;
    }
    setPreviewLoading(true);
    setPreviewError("");
    try {
      const result = await fetchSpeakAudio({
        text: language === "zh-CN" ? PREVIEW_TEXT_ZH : PREVIEW_TEXT_EN,
        voice: item.voice,
        engine: item.provider === "gemini" ? "gemini" : item.provider === "elevenlabs" ? "elevenlabs" : undefined,
      });
      setPreviewUrl(URL.createObjectURL(result.blob));
    } catch {
      setPreviewError(t("试听失败，请检查音色是否可用。", "Preview failed. Check if the voice is available."));
    } finally {
      setPreviewLoading(false);
    }
  }

  function handleAudioEnded() {
    setIsPlaying(false);
  }

  function handleAudioPlay() {
    setIsPlaying(true);
  }

  function handleAudioPause() {
    setIsPlaying(false);
  }

  return (
    <div className="vsTranscribeCard completed">
      {/* Cover */}
      <div className="vsTranscribeCardCover">
        <div
          className="vsTranscribeCardCoverBg"
          style={{
            background: `linear-gradient(135deg, ${palette[0]}, ${palette[1]} 60%, ${palette[2]})`,
          }}
        />
        <DiamondPattern color="rgba(255,255,255,0.8)" />
        <span className="vsTranscribeCardFormatBadge">
          {providerLabel ? `${providerLabel} · ${isDesign ? "Design" : "Clone"}` : isDesign ? "Design" : "Clone"}
        </span>
      </div>

      {/* Meta */}
      <div className="vsTranscribeCardMeta">
        <div className="vsTranscribeCardMetaTop">
          <span className="vsTranscribeCardTime">
            {item.target_model}
          </span>
        </div>
        <h4 className="vsTranscribeCardTitle" title={item.voice}>
          {item.name || item.voice}
        </h4>
        <p className="vsTranscribeCardPreview">
          {isDesign
            ? t("基于自然语言生成的专属音色", "Custom voice generated from description")
            : t("基于样本音频克隆的复刻音色", "Voice cloned from audio sample")}
        </p>
        {previewError && (
          <p className="vsTranscribeCardPreview error">{previewError}</p>
        )}
      </div>

      {/* Footer */}
      <div className="vsTranscribeCardFooter">
        <button
          type="button"
          className="vsVoiceCardPreviewBtn"
          onClick={(e) => {
            e.stopPropagation();
            void handlePreview();
          }}
          disabled={previewLoading}
          title={previewLoading ? t("试听生成中…", "Generating preview…") : isPlaying ? t("暂停", "Pause") : t("试听", "Preview")}
        >
          {previewLoading ? (
            <span className="spinner-mini" style={{ width: 14, height: 14 }} />
          ) : isPlaying ? (
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
              <rect x="6" y="4" width="4" height="16" rx="1" />
              <rect x="14" y="4" width="4" height="16" rx="1" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          )}
          <span>{previewLoading ? t("试听中…", "Loading…") : isPlaying ? t("暂停", "Pause") : t("试听", "Preview")}</span>
        </button>
        <button
          className="vsTranscribeCardDeleteBtn"
          onClick={onDelete}
          title={t("删除音色", "Delete voice")}
        >
          {t("删除", "Delete")}
        </button>
      </div>

      {/* Hidden audio element for preview playback */}
      {previewUrl && (
        <audio
          ref={audioRef}
          src={previewUrl}
          onPlay={handleAudioPlay}
          onPause={handleAudioPause}
          onEnded={handleAudioEnded}
          style={{ display: "none" }}
        />
      )}
    </div>
  );
};
