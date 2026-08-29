import { lazy, Suspense, useEffect, useState } from "react";
import { useI18n } from "../i18n";
const TtsPage = lazy(() => import("./TtsPage"));
const VoiceDesignPage = lazy(() => import("./VoiceDesignPage"));
const VoiceClonePage = lazy(() => import("./VoiceClonePage"));
const TranscriptionPage = lazy(() => import("./TranscriptionPage").then(m => ({ default: m.TranscriptionPage })));
import type { ErrorRuntimeContext } from "../types/ui";
import type { UseTtsResult } from "../hooks/useTts";
import type { VoiceCloneController, VoiceDesignController } from "../hooks/useVoiceManagement";

export type VoiceCenterSubTab = "tts" | "design" | "clone" | "transcribe";

type Props = {
  initialSubTab?: VoiceCenterSubTab;
  tts: UseTtsResult;
  design: VoiceDesignController;
  clone: VoiceCloneController;
  errorRuntimeContext: ErrorRuntimeContext;
  onSendToChat?: (text: string) => void;
  voiceProvider?: "qwen" | "xiaomi" | "gpt_sovits";
  onVoiceProviderChange?: (provider: "qwen" | "xiaomi" | "gpt_sovits") => void;
  onOpenSettings?: (provider?: string) => void;
};

export default function VoiceCenterPage({
  initialSubTab = "tts",
  tts,
  design,
  clone,
  errorRuntimeContext,
  onSendToChat,
  voiceProvider = "qwen",
  onVoiceProviderChange,
  onOpenSettings,
}: Props) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<VoiceCenterSubTab>(initialSubTab);
  const [isDetailMode, setIsDetailMode] = useState(false);

  useEffect(() => {
    setActiveTab(initialSubTab);
    setIsDetailMode(false);
  }, [initialSubTab]);

  const handleTabChange = (tab: VoiceCenterSubTab) => {
    setActiveTab(tab);
    setIsDetailMode(false);
  };

  const tabs = [
    { id: "tts" as const, label: t("文本到音频", "Text to Audio") },
    { id: "design" as const, label: t("设计音色", "Voice Design") },
    { id: "clone" as const, label: t("音色克隆", "Voice Clone") },
    { id: "transcribe" as const, label: t("一键转写", "Transcribe") },
  ];

  return (
    <div className={`vsVoiceCenter ${isDetailMode ? "vsVoiceCenter--immersive" : ""}`}>
      {!isDetailMode && (
        <div className="vsVoiceCenterNav">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => handleTabChange(tab.id)}
                className={`vsVoiceSubTab ${isActive ? "active" : ""}`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      )}

      <div className={`vsVoiceCenterContent ${isDetailMode ? "vsVoiceCenterContent--immersive" : ""}`}>
        <div className="vsVoiceCenterScroll">
          <Suspense fallback={<div className="vsPageLoading" />}>
          {activeTab === "tts" && (
             <div className="vsVoiceSubContent"><TtsPage tts={tts} errorRuntimeContext={errorRuntimeContext} /></div>
          )}
          {activeTab === "design" && (
             <div className="vsVoiceSubContent"><VoiceDesignPage design={design} errorRuntimeContext={errorRuntimeContext} voiceProvider={voiceProvider} onVoiceProviderChange={onVoiceProviderChange} onDetailModeChange={setIsDetailMode} /></div>
          )}
          {activeTab === "clone" && (
             <div className="vsVoiceSubContent"><VoiceClonePage clone={clone} errorRuntimeContext={errorRuntimeContext} voiceProvider={voiceProvider} onVoiceProviderChange={onVoiceProviderChange} onDetailModeChange={setIsDetailMode} /></div>
          )}
          {activeTab === "transcribe" && (
             <div className="vsVoiceSubContent"><TranscriptionPage onSendToChat={onSendToChat} onDetailModeChange={setIsDetailMode} onOpenSettings={onOpenSettings} /></div>
          )}
          </Suspense>
        </div>
      </div>
    </div>
  );
}
