import { useEffect, useMemo, useRef, useState } from "react";
import type { UseVoiceChatResult } from "../hooks/useVoiceChat";
import { formatModelHint, isVoiceRealtimeModel, type UseChatResult } from "../hooks/useChat";
import {
  DASHSCOPE_PROVIDER,
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

type ModelChoiceItem = {
  model: string;
  value: string;
  isRealtime: boolean;
};

type ProviderGroup = {
  provider: string;
  models: ModelChoiceItem[];
};

export default function VoiceCallSettingsPopover({ voiceChat, chat, t, disabled = false, onOpenSettings }: Props) {
  const [open, setOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(true);
  const [flyoutToLeft, setFlyoutToLeft] = useState(false);
  const [panelMaxHeight, setPanelMaxHeight] = useState(480);

  // Level 1: Selected / Hovered Provider ("" = fallback to active provider)
  const [activeProvider, setActiveProvider] = useState<string>("");
  // Level 2 -> Level 3 Flyout Category: "voice" | "translation" | ""
  const [activeCategory, setActiveCategory] = useState<"voice" | "translation" | "">("");
  // Level 2: Hovered Model ("" = fallback to active model)
  const [hoveredModel, setHoveredModel] = useState<string>("");

  const rootRef = useRef<HTMLDivElement>(null);

  // Build unified provider groups (merging catalog choices and realtime choices)
  const providerGroups = useMemo<ProviderGroup[]>(() => {
    const map = new Map<string, Map<string, ModelChoiceItem>>();

    // 1. Include all realtime choices from voiceChat
    for (const group of voiceChat.voiceChatRealtimeChoicesByProvider) {
      if (!map.has(group.provider)) {
        map.set(group.provider, new Map());
      }
      const providerMap = map.get(group.provider)!;
      for (const m of group.models) {
        providerMap.set(m, {
          model: m,
          value: `${group.provider}\u001f${m}`,
          isRealtime: true,
        });
      }
    }

    // 2. Merge all chatModelChoices (if available)
    if (chat && chat.chatModelChoices.length > 0) {
      for (const choice of chat.chatModelChoices) {
        if (!map.has(choice.provider)) {
          map.set(choice.provider, new Map());
        }
        const providerMap = map.get(choice.provider)!;
        if (!providerMap.has(choice.model)) {
          providerMap.set(choice.model, {
            model: choice.model,
            value: choice.value,
            isRealtime: isVoiceRealtimeModel(choice.provider, choice.model),
          });
        }
      }
    }

    return Array.from(map.entries()).map(([provider, modelMap]) => ({
      provider,
      models: Array.from(modelMap.values()),
    }));
  }, [chat, voiceChat.voiceChatRealtimeChoicesByProvider]);

  const currentProviderName = activeProvider || (chat ? chat.chatProvider : voiceChat.voiceChatProvider);
  const currentProviderGroup = providerGroups.find((g) => g.provider === currentProviderName) || providerGroups[0];

  const currentModelName =
    hoveredModel ||
    voiceChat.voiceChatModel ||
    (chat ? chat.chatModel : "");
  const isCurrentModelRealtime = isVoiceRealtimeModel(currentProviderName, currentModelName);

  const isLiveTranslateModel =
    isLiveTranslateModelHelper(currentProviderName, currentModelName) ||
    (currentModelName === voiceChat.voiceChatModel && voiceChat.voiceChatLiveTranslate);
  const isDashScopeLiveTranslate = currentProviderName === DASHSCOPE_PROVIDER && isLiveTranslateModel;
  // The 同传与复刻 (translation & voice-clone) category is a DashScope LiveTranslate
  // feature only. It must NOT appear for omni / audio voice models, plain chat models,
  // or any Google model (Google live-translate included).
  const canShowTranslationCategory = isDashScopeLiveTranslate;

  function handleModelSelect(provider: string, model: string) {
    setHoveredModel(model);
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

    const isRealtimeChoice = isVoiceRealtimeModel(provider, model);
    const isTranslateChoice = isLiveTranslateModelHelper(provider, model);

    if (isTranslateChoice) {
      // Auto-navigate to translation category in Level 3 for live-translate models
      setActiveProvider(provider);
      setActiveCategory("translation");
    } else if (isRealtimeChoice) {
      // Auto-navigate to voice category in Level 3 for voice models
      setActiveProvider(provider);
      setActiveCategory("voice");
    } else {
      // Standard text model choice: close popover
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

      // Clear active states on open so user starts cleanly at Level 1 / Level 2
      setActiveProvider("");
      setActiveCategory("");
      setHoveredModel("");
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

  const summaryText = isCurrentModelRealtime
    ? `${currentModelName} · ${secondaryLabel}`
    : currentModelName.trim()
    ? `${currentProviderName} / ${currentModelName}`
    : t("选择模型", "Select model");

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
          {/* LEVEL 1: PROVIDER SELECTION LIST (服务商) */}
          <div className="vsVoiceLevel1List">
            {providerGroups.map((group) => {
              const isSelectedProvider = group.provider === (chat ? chat.chatProvider : voiceChat.voiceChatProvider);
              const isActiveProvider = group.provider === (activeProvider || currentProviderName);
              return (
                <button
                  key={group.provider}
                  type="button"
                  className={`vsVoiceSettingsRow vsVoiceSettingsProviderRow${isActiveProvider ? " active" : ""}${isSelectedProvider ? " selected" : ""}`}
                  onMouseEnter={() => {
                    setActiveProvider(group.provider);
                    setActiveCategory("");
                    setHoveredModel("");
                  }}
                  onClick={() => {
                    setActiveProvider(group.provider);
                    setActiveCategory("");
                    setHoveredModel("");
                  }}
                >
                  <span className="vsVoiceSettingsProviderCheck" aria-hidden="true">
                    {isSelectedProvider ? "✓" : ""}
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

          {/* LEVEL 2: SPECIFIC MODELS LIST (具体的模型) */}
          {currentProviderGroup ? (
            <div
              className={`vsModelFlyout${flyoutToLeft ? " flyLeft" : ""}`}
              style={{ maxHeight: `${panelMaxHeight}px` }}
            >
              {/* List of Specific Models under Active Provider */}
              <div className="vsVoiceSettingsList">
                {currentProviderGroup.models.map((item) => {
                  const isSelectedModel =
                    currentProviderGroup.provider === (chat ? chat.chatProvider : voiceChat.voiceChatProvider) &&
                    item.model === (chat ? chat.chatModel : voiceChat.voiceChatModel);
                  const hint = formatModelHint(currentProviderGroup.provider, item.model, t);
                  return (
                    <button
                      key={item.value}
                      type="button"
                      className={`vsVoiceSettingsRow${isSelectedModel ? " selected" : ""}`}
                      aria-current={isSelectedModel ? "true" : undefined}
                      onMouseEnter={() => {
                        setHoveredModel(item.model);
                        if (isLiveTranslateModelHelper(currentProviderGroup.provider, item.model)) {
                          setActiveCategory("translation");
                        } else if (item.isRealtime) {
                          setActiveCategory("voice");
                        }
                      }}
                      onClick={() => handleModelSelect(currentProviderGroup.provider, item.model)}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                        <span className="vsVoiceSettingsRowLabel">{item.model}</span>
                        {item.isRealtime ? (
                          <span className="vsVoiceSettingsProviderChevron" aria-hidden="true" style={{ fontSize: 12, opacity: 0.6 }}>
                            ›
                          </span>
                        ) : null}
                      </div>
                      {hint ? <span className="vsVoiceSettingsRowHint">{hint}</span> : null}
                    </button>
                  );
                })}
              </div>

              {/* Option Shortcuts for Voice & Translation Settings */}
              <div style={{ marginTop: 6, paddingTop: 4, borderTop: "1px solid var(--line)", display: "flex", flexDirection: "column", gap: 2 }}>
                <button
                  type="button"
                  className={`vsVoiceSettingsRow${activeCategory === "voice" ? " selected" : ""}`}
                  onMouseEnter={() => setActiveCategory("voice")}
                  onClick={() => setActiveCategory("voice")}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                    <span className="vsVoiceSettingsRowLabel">🎤 {t("音色设定", "Voices")}</span>
                    <span className="vsVoiceSettingsProviderChevron" aria-hidden="true">›</span>
                  </div>
                </button>
                {canShowTranslationCategory ? (
                  <button
                    type="button"
                    className={`vsVoiceSettingsRow${activeCategory === "translation" ? " selected" : ""}`}
                    onMouseEnter={() => setActiveCategory("translation")}
                    onClick={() => setActiveCategory("translation")}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                      <span className="vsVoiceSettingsRowLabel">🌐 {t("同传与复刻", "Translation")}</span>
                      <span className="vsVoiceSettingsProviderChevron" aria-hidden="true">›</span>
                    </div>
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {/* LEVEL 3: VOICE TIMBRE & TRANSLATION SETTINGS (音色与同传/扩展设定) */}
          {activeCategory ? (
            <div className={`vsVoiceLevel3Flyout${flyoutToLeft ? " flyLeft" : ""}`}>
              {/* Category Tab Bar at top of Level 3 */}
              <div className="vsCascadingTabBar">
                <button
                  type="button"
                  className={`vsCascadingTabItem${activeCategory === "voice" ? " active" : ""}`}
                  onClick={() => setActiveCategory("voice")}
                >
                  🎤 {t("音色设定", "Voices")}
                </button>
                {canShowTranslationCategory ? (
                  <button
                    type="button"
                    className={`vsCascadingTabItem${activeCategory === "translation" ? " active" : ""}`}
                    onClick={() => setActiveCategory("translation")}
                  >
                    🌐 {t("同传与复刻", "Translation")}
                  </button>
                ) : null}
              </div>

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
                    <>
                      <div
                        className="vsTranslationModeSegment"
                        style={{ justifyContent: "center", padding: "6px 12px", fontSize: 12, opacity: 0.9 }}
                      >
                        <span>{t("单向同传 (翻译为目标语言)", "Unidirectional (Translate to Target)")}</span>
                      </div>

                      {/* Preset Target Languages for Qwen LiveTranslate */}
                      <div className="vsPresetPairSection" style={{ marginTop: 8 }}>
                        <div className="vsPresetSubTitle">{t("常用目标语", "Target languages")}</div>
                        <div className="vsPresetPillsGroup">
                          {[
                            { label: "英语", code: "en" },
                            { label: "日语", code: "ja" },
                            { label: "韩语", code: "ko" },
                            { label: "法语", code: "fr" },
                            { label: "德语", code: "de" },
                            { label: "西班牙语", code: "es" },
                          ].map((item) => {
                            const active = voiceChat.voiceChatTargetLanguageCode === item.code;
                            return (
                              <button
                                key={`tgt-pill-${item.code}`}
                                type="button"
                                className={`vsPresetPillBtn${active ? " active" : ""}`}
                                onClick={() => voiceChat.onTargetLanguageCodeChange(item.code)}
                              >
                                {item.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Single Full-Width Target Language Selector */}
                      <div className="vsLanguageSelectorBox" style={{ marginTop: 8, flexDirection: "column", gap: 6 }}>
                        <div className="vsLanguageSelectGroup" style={{ width: "100%" }}>
                          <label className="vsLanguageSelectLabel">{t("🎯 目标同传语言", "🎯 Target Language")}</label>
                          <select
                            className="vsLanguageSelectDropdown"
                            style={{ width: "100%" }}
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
                    </>
                  ) : (
                    <>
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

                      {/* Dual Language Selector */}
                      <div className="vsLanguageSelectorBox">
                        <div className="vsLanguageSelectGroup">
                          <label className="vsLanguageSelectLabel">
                            {voiceChat.voiceChatTranslationMode === "bidirectional"
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
                            {voiceChat.voiceChatTranslationMode === "bidirectional"
                              ? t("语言 B", "Language B")
                              : t("🎯 目标语言", "🎯 Target Lang")}
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
                    </>
                  )}

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
