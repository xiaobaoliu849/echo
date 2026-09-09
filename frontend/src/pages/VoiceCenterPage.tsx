import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";
const TtsPage = lazy(() => import("./TtsPage"));
const VoiceDesignPage = lazy(() => import("./VoiceDesignPage"));
const VoiceClonePage = lazy(() => import("./VoiceClonePage"));
const TranscriptionPage = lazy(() => import("./TranscriptionPage").then(m => ({ default: m.TranscriptionPage })));
import type { ErrorRuntimeContext } from "../types/ui";
import type { UseTtsResult } from "../hooks/useTts";
import type { VoiceCloneController, VoiceDesignController, VoiceProviderId } from "../hooks/useVoiceManagement";

export type VoiceCenterSubTab = "tts" | "design" | "clone" | "transcribe";
export type VoiceCenterVoiceProvider = VoiceProviderId;

type Props = {
  initialSubTab?: VoiceCenterSubTab;
  tts: UseTtsResult;
  design: VoiceDesignController;
  clone: VoiceCloneController;
  errorRuntimeContext: ErrorRuntimeContext;
  onSendToChat?: (text: string) => void;
  voiceProvider?: VoiceProviderId;
  onVoiceProviderChange?: (provider: VoiceProviderId) => void;
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
  const [isTtsDropdownOpen, setIsTtsDropdownOpen] = useState(false);
  const ttsMenuRef = useRef<HTMLDivElement>(null);
  const ttsMenuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setActiveTab(initialSubTab);
    setIsDetailMode(false);
  }, [initialSubTab]);

  const closeTtsMenu = (restoreFocus = false) => {
    setIsTtsDropdownOpen(false);
    if (restoreFocus) ttsMenuButtonRef.current?.focus();
  };

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ttsMenuRef.current && !ttsMenuRef.current.contains(event.target as Node)) {
        setIsTtsDropdownOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeTtsMenu(true);
      }
    }
    if (isTtsDropdownOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
        document.removeEventListener("keydown", handleKeyDown);
      };
    }
  }, [isTtsDropdownOpen]);

  const handleTabChange = (tab: VoiceCenterSubTab) => {
    setActiveTab(tab);
    setIsDetailMode(false);
    closeTtsMenu();
  };

  const ttsModes = [
    {
      id: "text" as const,
      icon: "📄",
      label: t("文本转语音", "Text to speech"),
      desc: t("单人自然朗读 · 适合正文与旁白", "Single natural speaker for narration & prose"),
    },
    {
      id: "dialogue" as const,
      icon: "👥",
      label: t("对话转语音", "Dialogue to speech"),
      desc: t("双人角色对谈 · 适合播客与情景剧", "Two-speaker dialogue for podcasts & role-play"),
    },
    {
      id: "pdf" as const,
      icon: "📑",
      label: t("PDF 转语音", "PDF to speech"),
      desc: t("PDF 文档提炼 · 支持 AI 口语化润色", "Extract from PDF with AI oralization polishing"),
    },
  ];

  const currentTtsMode = ttsModes.find((m) => m.id === tts.ttsMode) || ttsModes[0];

  const otherTabs = [
    { id: "design" as const, label: t("设计音色", "Voice Design"), icon: "✨" },
    { id: "clone" as const, label: t("音色克隆", "Voice Clone"), icon: "🧬" },
    { id: "transcribe" as const, label: t("一键转写", "Transcribe"), icon: "📝" },
  ];

  return (
    <div className={`vsVoiceCenter ${isDetailMode ? "vsVoiceCenter--immersive" : ""}`}>
      {!isDetailMode && (
        <div className="vsVoiceCenterNav">
          <div className="vsVoiceCenterSegmented">
            {/* 1st Tab: TTS Mode Dropdown Tab — unified single button with inline chevron */}
            <div className="vsVoiceSubTabDropdownWrapper" ref={ttsMenuRef}>
              <div className={`vsVoiceSubTabDropdownGroup ${activeTab === "tts" ? "active" : ""}`}>
                <button
                  type="button"
                  ref={ttsMenuButtonRef}
                  data-testid="voicecenter-tab-tts"
                  onClick={() => {
                    if (activeTab !== "tts") {
                      handleTabChange("tts");
                    } else {
                      setIsTtsDropdownOpen((prev) => !prev);
                    }
                  }}
                  aria-expanded={isTtsDropdownOpen}
                  aria-haspopup="menu"
                  className={`vsVoiceSubTab vsVoiceSubTab--unified ${activeTab === "tts" ? "active" : ""}`}
                >
                  <span className="vsVoiceSubTabIcon" aria-hidden="true">{currentTtsMode.icon}</span>
                  <span className="vsVoiceSubTabLabel">{currentTtsMode.label}</span>
                  <svg
                    className={`vsVoiceSubTabChevron vsVoiceSubTabChevron--inline ${isTtsDropdownOpen && activeTab === "tts" ? "open" : ""}`}
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>
              </div>

              <div
                className={`vsVoiceSubTabMenu ${isTtsDropdownOpen ? "open" : ""}`}
                role="menu"
                aria-label={t("创作模式选择", "TTS Mode selection")}
              >
                {ttsModes.map((opt) => {
                  const isSelected = tts.ttsMode === opt.id && activeTab === "tts";
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      role="menuitem"
                      aria-label={opt.label}
                      className={`vsVoiceSubTabMenuItem ${isSelected ? "active" : ""}`}
                      onClick={() => {
                        if (tts.ttsMode !== opt.id) tts.onTtsModeChange(opt.id);
                        handleTabChange("tts");
                      }}
                    >
                      <span className="vsVoiceSubTabMenuIcon" aria-hidden="true">{opt.icon}</span>
                      <div className="vsVoiceSubTabMenuText">
                        <span className="vsVoiceSubTabMenuTitle">{opt.label}</span>
                        <span className="vsVoiceSubTabMenuDesc">{opt.desc}</span>
                      </div>
                      {isSelected && (
                        <span className="vsVoiceSubTabMenuCheckmark" aria-hidden="true">✓</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Other Tabs */}
            {otherTabs.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => handleTabChange(tab.id)}
                  className={`vsVoiceSubTab ${isActive ? "active" : ""}`}
                >
                  <span className="vsVoiceSubTabIcon" aria-hidden="true">{tab.icon}</span>
                  <span className="vsVoiceSubTabLabel">{tab.label}</span>
                </button>
              );
            })}
          </div>
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
