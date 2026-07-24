import { useEffect, useRef, useState } from "react";
import type { UseVoiceChatResult } from "../hooks/useVoiceChat";
import { formatModelHint, type UseChatResult } from "../hooks/useChat";
import {
  DASHSCOPE_PROVIDER,
  GOOGLE_PROVIDER,
  PRESET_LANGUAGE_PAIRS,
  formatVoiceChatSecondaryLabel,
  isLiveTranslateModel as isLiveTranslateModelHelper,
} from "../hooks/useVoiceChatHelpers";

type Translator = (zh: string, en: string) => string;

type Props = {
  voiceChat: UseVoiceChatResult;
  chat?: UseChatResult;
  t: Translator;
  disabled?: boolean;
  onOpenSettings?: () => void;
};

export default function VoiceCallSettingsPopover({ voiceChat, chat, t, disabled = false, onOpenSettings }: Props) {
  const [open, setOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(true);
  const [flyoutToLeft, setFlyoutToLeft] = useState(false);
  const [panelMaxHeight, setPanelMaxHeight] = useState(480);
  
  // Level 1: Selected / Hovered Provider
  const [activeProvider, setActiveProvider] = useState<string>("");
  // Level 2: Selected / Hovered Category ("model" | "voice" | "translation" | "")
  const [activeCategory, setActiveCategory] = useState<"model" | "voice" | "translation" | "">("");

  const rootRef = useRef<HTMLDivElement>(null);

  const currentSelectedProvider = activeProvider || voiceChat.voiceChatProvider;

  const currentProviderGroup = voiceChat.voiceChatRealtimeChoicesByProvider.find(
    (g) => g.provider === currentSelectedProvider
  ) || voiceChat.voiceChatRealtimeChoicesByProvider[0];

  const isLiveTranslateModel =
    voiceChat.voiceChatLiveTranslate ||
    isLiveTranslateModelHelper(currentSelectedProvider, voiceChat.voiceChatModel);
  const isDashScopeLiveTranslate =
    currentSelectedProvider === DASHSCOPE_PROVIDER && isLiveTranslateModel;
  const canShowTranslationCategory =
    isLiveTranslateModel ||
    currentSelectedProvider === DASHSCOPE_PROVIDER ||
    currentSelectedProvider === GOOGLE_PROVIDER;

  function handleModelSelect(provider: string, model: string) {
    if (chat) {
      if (provider !== chat.chatProvider) {
        chat.onProviderChange(provider);
      }
      chat.onModelChoiceChange(`${provider}\u001f${model}`);
    }
    if (provider !== voiceChat.voiceChatProvider) {
      voiceChat.onProviderChange(provider);
    }
    voiceChat.onModelChange(model);

    if (isLiveTranslateModelHelper(provider, model)) {
      // For live-translate models, do not close popover immediately. Instead,
      // auto-navigate to translation settings category so the user can configure
      // target language, voice clone, and tone in the same interaction flow.
      setActiveProvider(provider);
      setActiveCategory("translation");
    } else {
      // Leaf selection for standard models = explicit choice: close so updated summary confirms it
      setOpen(false);
    }
  }

  function handleToggle() {
    if (!open && rootRef.current) {
      const rect = rootRef.current.getBoundingClientRect();
      const margin = 16;
      const spaceAbove = rect.top - margin;
      const spaceBelow = window.innerHeight - rect.bottom - margin;
      const upward = spaceAbove >= spaceBelow;
      setOpenUpward(upward);
      setFlyoutToLeft(rect.left + 660 > window.innerWidth);
      setPanelMaxHeight(Math.max(200, Math.min(520, upward ? spaceAbove : spaceBelow)));
      
      // Clear active states when toggling so user starts strictly at Level 1
      setActiveProvider("");
      setActiveCategory("");
    }
    setOpen((prev) => !prev);
  }

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  // Secondary label next to the model name: Voice Clone takes precedence, and
  // live-translate models show the language pair instead of a stale voice label.
  const secondaryLabel = formatVoiceChatSecondaryLabel({
    liveTranslate: voiceChat.voiceChatLiveTranslate,
    voiceCloneEnabled: Boolean(voiceChat.voiceChatEnableVoiceClone),
    translationMode: voiceChat.voiceChatTranslationMode,
    sourceLanguageCode: voiceChat.voiceChatSourceLanguageCode,
    targetLanguageCode: voiceChat.voiceChatTargetLanguageCode,
    voiceLabel: voiceChat.voiceChatVoiceLabel,
    provider: voiceChat.voiceChatProvider,
    model: voiceChat.voiceChatModel,
    t,
  });

  const summaryText = `${voiceChat.voiceChatModel} · ${secondaryLabel}`;

  return (
    <div className="vsVoiceSettings" ref={rootRef}>
      <button
        type="button"
        className="vsVoiceSettingsSummary"
        onClick={handleToggle}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={t("通话设置", "Call settings")}
      >
        <span className="vsVoiceSettingsSummaryText">{summaryText}</span>
        <svg
          className="vsVoiceSettingsSummaryChevron"
          width="10"
          height="6"
          viewBox="0 0 10 6"
          fill="none"
          aria-hidden="true"
        >
          <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open ? (
        <div
          className={`vsVoiceSettingsPanel${openUpward ? "" : " below"}`}
          style={{ maxHeight: `${panelMaxHeight}px` }}
          role="dialog"
          aria-label={t("通话设置", "Call settings")}
        >
          {/* LEVEL 1: PROVIDER SELECTION LIST */}
          <div className="vsVoiceLevel1List">
            {voiceChat.voiceChatRealtimeChoicesByProvider.map((group) => {
              const isCurrentProvider = group.provider === voiceChat.voiceChatProvider;
              const isActiveProvider = group.provider === activeProvider;
              return (
                <button
                  key={group.provider}
                  type="button"
                  className={`vsVoiceSettingsRow vsVoiceSettingsProviderRow${isActiveProvider ? " active" : ""}${isCurrentProvider ? " selected" : ""}`}
                  onMouseEnter={() => {
                    setActiveProvider(group.provider);
                    setActiveCategory("");
                  }}
                  onClick={() => {
                    setActiveProvider(group.provider);
                    setActiveCategory("");
                  }}
                >
                  <span className="vsVoiceSettingsProviderCheck" aria-hidden="true">
                    {isCurrentProvider ? "✓" : ""}
                  </span>
                  <span className="vsVoiceSettingsRowLabel">{group.provider}</span>
                  <span className="vsVoiceSettingsProviderChevron" aria-hidden="true">›</span>
                </button>
              );
            })}

            <div
              className="vsVoiceSettingsFooter"
              style={{ marginTop: 4, paddingTop: 4, borderTop: "1px solid var(--line)", display: "flex", gap: 4 }}
            >
              {onOpenSettings ? (
                <button
                  type="button"
                  className="vsVoiceSettingsRow vsVoiceSettingsManageRow"
                  style={{ flex: 1 }}
                  onClick={() => {
                    setOpen(false);
                    onOpenSettings();
                  }}
                >
                  <span className="vsVoiceSettingsRowLabel">{t("管理模型", "Manage models")}</span>
                </button>
              ) : null}
              <button
                type="button"
                className="vsVoiceSettingsRow vsVoiceSettingsDoneRow"
                style={{ flex: 1, justifyContent: "center", fontWeight: 600 }}
                onClick={() => setOpen(false)}
              >
                <span className="vsVoiceSettingsRowLabel">{t("完成", "Done")}</span>
              </button>
            </div>
          </div>

          {/* LEVEL 2: CATEGORY SELECTION MENU (Flies out to the right/left ONLY when a Provider is hovered) */}
          {activeProvider ? (
            <div className={`vsVoiceLevel2Flyout${flyoutToLeft ? " flyLeft" : ""}`}>
              <button
                type="button"
                className={`vsVoiceSettingsRow${activeCategory === "model" ? " selected" : ""}`}
                onMouseEnter={() => setActiveCategory("model")}
                onClick={() => setActiveCategory("model")}
              >
                <span className="vsVoiceSettingsRowLabel">🤖 {t("模型列表", "Models")}</span>
                <span className="vsVoiceSettingsProviderChevron" aria-hidden="true">›</span>
              </button>
              <button
                type="button"
                className={`vsVoiceSettingsRow${activeCategory === "voice" ? " selected" : ""}`}
                onMouseEnter={() => setActiveCategory("voice")}
                onClick={() => setActiveCategory("voice")}
              >
                <span className="vsVoiceSettingsRowLabel">🎙️ {t("音色设定", "Voices")}</span>
                <span className="vsVoiceSettingsProviderChevron" aria-hidden="true">›</span>
              </button>
              {canShowTranslationCategory ? (
                <button
                  type="button"
                  className={`vsVoiceSettingsRow${activeCategory === "translation" ? " selected" : ""}`}
                  onMouseEnter={() => setActiveCategory("translation")}
                  onClick={() => setActiveCategory("translation")}
                >
                  <span className="vsVoiceSettingsRowLabel">🌐 {t("同传与复刻", "Translation")}</span>
                  <span className="vsVoiceSettingsProviderChevron" aria-hidden="true">›</span>
                </button>
              ) : null}
            </div>
          ) : null}

          {/* LEVEL 3: SPECIFIC CONTENT PANEL (Flies out to the right/left ONLY when a Category is hovered) */}
          {activeCategory ? (
            <div className={`vsVoiceLevel3Flyout${flyoutToLeft ? " flyLeft" : ""}`}>
              {/* LEVEL 3 - MODEL LIST */}
              {activeCategory === "model" && currentProviderGroup ? (
                <div className="vsVoiceSettingsList">
                  {currentProviderGroup.models.map((model) => {
                    const isCurrentModel =
                      currentProviderGroup.provider === voiceChat.voiceChatProvider &&
                      model === voiceChat.voiceChatModel;
                    const hint = formatModelHint(currentProviderGroup.provider, model, t);
                    return (
                      <button
                        key={model}
                        type="button"
                        className={`vsVoiceSettingsRow${isCurrentModel ? " selected" : ""}`}
                        aria-current={isCurrentModel ? "true" : undefined}
                        onClick={() => handleModelSelect(currentProviderGroup.provider, model)}
                      >
                        <span className="vsVoiceSettingsRowLabel">{model}</span>
                        {hint ? <span className="vsVoiceSettingsRowHint">{hint}</span> : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {/* LEVEL 3 - VOICE LIST */}
              {activeCategory === "voice" ? (
                <div className="vsVoiceSettingsSection">
                  {voiceChat.voiceChatEnableVoiceClone ? (
                    <div
                      className="vsVoiceCloneActiveBadge"
                      style={{
                        padding: "8px 12px",
                        marginBottom: 8,
                        background: "rgba(96, 165, 250, 0.12)",
                        border: "1px solid rgba(96, 165, 250, 0.3)",
                        borderRadius: 8,
                        fontSize: 12,
                        color: "#60a5fa",
                      }}
                    >
                      ✨ {t("声音复刻已激活：将使用您本人的声音朗读外语", "Voice Clone active: Speaking in your own voice")}
                    </div>
                  ) : null}
                  <div className="vsVoiceSettingsList" style={{ maxHeight: 300, overflowY: "auto" }}>
                    {voiceChat.voiceChatVoiceOptions.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        className={`vsVoiceSettingsRow${
                          !voiceChat.voiceChatEnableVoiceClone && item.value === voiceChat.voiceChatVoice
                            ? " selected"
                            : ""
                        }`}
                        onClick={() => {
                          if (voiceChat.voiceChatEnableVoiceClone) {
                            voiceChat.onVoiceCloneToggle?.(false);
                          }
                          voiceChat.onVoiceChange(item.value);
                          // Leaf selection = explicit choice: close so the updated summary pill confirms it
                          setOpen(false);
                        }}
                      >
                        <span className="vsVoiceSettingsRowLabel">{item.label}</span>
                        {item.description ? (
                          <span className="vsVoiceSettingsRowHint">{item.description}</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {/* LEVEL 3 - TRANSLATION & VOICE CLONE */}
              {activeCategory === "translation" ? (
                <div className="vsVoiceSettingsSection vsVoiceTranslationCard" style={{ width: 310 }}>
                  {isDashScopeLiveTranslate ? (
                    <div
                      className="vsTranslationModeSegment"
                      style={{ justifyContent: "center", padding: "6px 12px", fontSize: 12, opacity: 0.9 }}
                    >
                      <span>{t("单向同传 (源语言 → 目标语言)", "Unidirectional (Source → Target)")}</span>
                    </div>
                  ) : (
                    <div className="vsTranslationModeSegment">
                      <button
                        type="button"
                        className={voiceChat.voiceChatTranslationMode === "bidirectional" ? "active" : ""}
                        onClick={() => voiceChat.onTranslationModeChange("bidirectional")}
                      >
                        {t("双向互翻 ⇄", "Bidirectional ⇄")}
                      </button>
                      <button
                        type="button"
                        className={voiceChat.voiceChatTranslationMode === "unidirectional" ? "active" : ""}
                        onClick={() => voiceChat.onTranslationModeChange("unidirectional")}
                      >
                        {t("单向翻译 →", "Single Direction →")}
                      </button>
                    </div>
                  )}

                  {/* Preset Language Pairs */}
                  <div className="vsPresetPairSection">
                    <div className="vsPresetSubTitle">{t("常用语对", "Preset pairs")}</div>
                    <div className="vsPresetPillsGroup">
                      {PRESET_LANGUAGE_PAIRS.map((pair) => {
                        const active =
                          voiceChat.voiceChatSourceLanguageCode === pair.source &&
                          voiceChat.voiceChatTargetLanguageCode === pair.target;
                        return (
                          <button
                            key={`${pair.source}-${pair.target}`}
                            type="button"
                            className={`vsPresetPillBtn${active ? " active" : ""}`}
                            onClick={() => voiceChat.onPresetLanguagePairSelect(pair.source, pair.target)}
                          >
                            {pair.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Language Selector */}
                  <div className="vsLanguageSelectorBox">
                    <div className="vsLanguageSelectGroup">
                      <label className="vsLanguageSelectLabel">
                        {!isDashScopeLiveTranslate && voiceChat.voiceChatTranslationMode === "bidirectional"
                          ? t("语言 A", "Language A")
                          : t("源语言", "Source Lang")}
                      </label>
                      <select
                        className="vsLanguageSelectDropdown"
                        value={voiceChat.voiceChatSourceLanguageCode}
                        onChange={(e) => voiceChat.onSourceLanguageCodeChange(e.target.value)}
                      >
                        {voiceChat.voiceChatTargetLanguageOptions.map((opt) => (
                          <option key={`src-${opt.value}`} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    <button
                      type="button"
                      className="vsVoiceSettingsSwapBtn"
                      title={t("一键颠倒语言", "Swap languages")}
                      onClick={voiceChat.onSwapLanguages}
                    >
                      ⇄
                    </button>

                    <div className="vsLanguageSelectGroup">
                      <label className="vsLanguageSelectLabel">
                        {!isDashScopeLiveTranslate && voiceChat.voiceChatTranslationMode === "bidirectional"
                          ? t("语言 B", "Language B")
                          : t("目标语言", "Target Lang")}
                      </label>
                      <select
                        className="vsLanguageSelectDropdown"
                        value={voiceChat.voiceChatTargetLanguageCode}
                        onChange={(e) => voiceChat.onTargetLanguageCodeChange(e.target.value)}
                      >
                        {voiceChat.voiceChatTargetLanguageOptions.map((opt) => (
                          <option key={`tgt-${opt.value}`} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Single Direction Echo Checkbox */}
                  {voiceChat.voiceChatTranslationMode === "unidirectional" ? (
                    <label
                      className="vsVoiceSettingsEcho"
                      title={t("输入已经是目标语言时也朗读出来", "Echo speech that is already in the target language")}
                    >
                      <input
                        type="checkbox"
                        checked={voiceChat.voiceChatEchoTargetLanguage}
                        onChange={(e) => voiceChat.onEchoTargetLanguageChange(e.target.checked)}
                      />
                      <span>{t("同语回放", "Echo target language")}</span>
                    </label>
                  ) : null}

                  {/* DashScope Voice Clone Controls */}
                  {isDashScopeLiveTranslate ? (
                    <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
                      <label
                        className="vsVoiceSettingsEcho"
                        title={t("自动提取您的发言声纹，并使用您本人的音色朗读外语", "Extract your voiceprint and speak target languages in your own voice")}
                        style={{ marginBottom: voiceChat.voiceChatEnableVoiceClone ? 8 : 0 }}
                      >
                        <input
                          type="checkbox"
                          checked={voiceChat.voiceChatEnableVoiceClone || false}
                          onChange={(e) => voiceChat.onVoiceCloneToggle?.(e.target.checked)}
                        />
                        <span style={{ fontWeight: 600, color: "#60a5fa" }}>
                          {t("声音复刻 (用本人音色朗读)", "Voice Clone (Speak in your own voice)")}
                        </span>
                      </label>

                      {voiceChat.voiceChatEnableVoiceClone ? (
                        <div className="vsPresetPillsGroup" style={{ marginTop: 6 }}>
                          <button
                            type="button"
                            className={`vsPresetPillBtn ${voiceChat.voiceChatVoiceCloneFrequency === "once" ? "active" : ""}`}
                            onClick={() => voiceChat.onVoiceCloneFrequencyChange?.("once")}
                            title={t("服务端录入首句声纹并在会话内持续使用", "Clone voice from first utterance and reuse")}
                          >
                            {t("单人实时复刻", "Single Speaker (Once)")}
                          </button>
                          <button
                            type="button"
                            className={`vsPresetPillBtn ${voiceChat.voiceChatVoiceCloneFrequency === "always" ? "active" : ""}`}
                            onClick={() => voiceChat.onVoiceCloneFrequencyChange?.("always")}
                            title={t("每次发声均动态捕获声纹特征，适合多人对话", "Dynamically capture voice per utterance")}
                          >
                            {t("动态实时复刻", "Multi Speaker (Always)")}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
