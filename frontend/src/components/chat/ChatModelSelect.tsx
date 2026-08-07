import { useEffect, useMemo, useRef, useState } from "react";
import { formatModelHint, type UseChatResult } from "../../hooks/useChat";
import { useProviderFlyoutTop } from "../../hooks/useProviderFlyoutTop";

type Translator = (zh: string, en: string) => string;

type Props = {
  chat: UseChatResult;
  t: Translator;
  onOpenSettings?: () => void;
};

type ModelGroup = {
  provider: string;
  choices: { model: string; value: string }[];
};

export default function ChatModelSelect({ chat, t, onOpenSettings }: Props) {
  const [open, setOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(true);
  const [flyoutToLeft, setFlyoutToLeft] = useState(false);
  const [panelMaxHeight, setPanelMaxHeight] = useState(480);
  // Level 1: hovered provider ("" = nothing hovered yet, Level 2 hidden)
  const [activeProvider, setActiveProvider] = useState<string>("");

  const rootRef = useRef<HTMLDivElement>(null);
  const { panelRef, onRowRef, flyoutTop } = useProviderFlyoutTop(open, activeProvider);

  const groups = useMemo<ModelGroup[]>(() => {
    const byProvider = new Map<string, ModelGroup>();
    for (const choice of chat.chatModelChoices) {
      let group = byProvider.get(choice.provider);
      if (!group) {
        group = { provider: choice.provider, choices: [] };
        byProvider.set(choice.provider, group);
      }
      group.choices.push({ model: choice.model, value: choice.value });
    }
    return [...byProvider.values()];
  }, [chat.chatModelChoices]);

  const activeGroup = groups.find((g) => g.provider === activeProvider) || null;

  const summaryText = chat.chatModel.trim()
    ? `${chat.chatProvider} / ${chat.chatModel}`
    : t("选择模型", "Select model");

  function handleToggle() {
    if (!open && rootRef.current) {
      const rect = rootRef.current.getBoundingClientRect();
      const margin = 16;
      const spaceAbove = rect.top - margin;
      const spaceBelow = window.innerHeight - rect.bottom - margin;
      const upward = spaceAbove >= spaceBelow;
      setOpenUpward(upward);
      setFlyoutToLeft(rect.left + 560 > window.innerWidth);
      setPanelMaxHeight(Math.max(200, Math.min(520, upward ? spaceAbove : spaceBelow)));
      // Reset hover state so the user starts strictly at Level 1
      setActiveProvider("");
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

  return (
    <div className="vsVoiceSettings vsModelSelectRoot" ref={rootRef}>
      <button
        type="button"
        className="vsVoiceSettingsSummary"
        onClick={handleToggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={t("切换模型", "Switch model")}
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
          ref={panelRef}
          role="dialog"
          aria-label={t("切换模型", "Switch model")}
        >
          {/* LEVEL 1: PROVIDER LIST */}
          <div className="vsVoiceLevel1List">
            {groups.map((group) => {
              const isCurrentProvider = group.provider === chat.chatProvider;
              const isActiveProvider = group.provider === activeProvider;
              return (
                <button
                  key={group.provider}
                  type="button"
                  className={`vsVoiceSettingsRow vsVoiceSettingsProviderRow${isActiveProvider ? " active" : ""}${isCurrentProvider ? " selected" : ""}`}
                  ref={(el) => onRowRef(group.provider, el)}
                  onMouseEnter={() => setActiveProvider(group.provider)}
                  onClick={() => setActiveProvider(group.provider)}
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

          {/* LEVEL 2: MODEL FLYOUT (flies out to the right/left ONLY when a Provider is hovered) */}
          {activeGroup ? (
            <div
              className={`vsModelFlyout${flyoutToLeft ? " flyLeft" : ""}`}
              style={{ top: flyoutTop, maxHeight: `${panelMaxHeight}px` }}
            >
              {activeGroup.choices.map((choice) => {
                const isCurrentModel =
                  activeGroup.provider === chat.chatProvider && choice.model === chat.chatModel;
                const hint = formatModelHint(activeGroup.provider, choice.model, t);
                return (
                  <button
                    key={choice.value}
                    type="button"
                    className={`vsVoiceSettingsRow${isCurrentModel ? " selected" : ""}`}
                    aria-current={isCurrentModel ? "true" : undefined}
                    onClick={() => {
                      chat.onModelChoiceChange(choice.value);
                      setOpen(false);
                    }}
                  >
                    <span className="vsVoiceSettingsRowLabel">{choice.model}</span>
                    {hint ? <span className="vsVoiceSettingsRowHint">{hint}</span> : null}
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
