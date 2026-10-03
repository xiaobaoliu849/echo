import { useState } from "react";
import type { UseVoiceChatResult } from "../hooks/useVoiceChat";
import { GEMINI_LIVE_ACCENTS } from "../utils/geminiLivePreferences";

type Props = {
  voiceChat: UseVoiceChatResult;
  t: (zh: string, en: string) => string;
  onChangeModel: () => void;
  onDone: () => void;
};

// Ben is documented; Ben and Leo both passed a real regional Cloud handshake
// on 2026-10-03. Do not add guessed face names to this list.
const PREBUILT_AVATARS = ["Ben", "Leo"];

/** Face, voice and accent are independent session preferences. */
export default function LiveAvatarSettings({ voiceChat, t, onChangeModel, onDone }: Props) {
  const [useCustomName, setUseCustomName] = useState(!PREBUILT_AVATARS.includes(voiceChat.voiceChatAvatarName));
  const validName = Boolean(voiceChat.voiceChatAvatarName.trim());
  return (
    <div className="vsAvatarPreferences">
      <div className="vsAvatarPreferencesHeading">
        <div>
          <strong>{t("视频分身", "Live Avatar")}</strong>
          <span>Gemini 3.8 Live</span>
        </div>
        <button type="button" className="vsAvatarTextButton" onClick={onChangeModel}>
          {t("切换模型", "Change model")}
        </button>
      </div>
      <label>
        <span>{t("形象", "Avatar")}</span>
        <select value={useCustomName ? "custom" : voiceChat.voiceChatAvatarName} onChange={(e) => {
          const custom = e.target.value === "custom";
          setUseCustomName(custom);
          if (!custom) voiceChat.onAvatarNameChange(e.target.value);
          else if (PREBUILT_AVATARS.includes(voiceChat.voiceChatAvatarName)) voiceChat.onAvatarNameChange("");
        }}>
          {PREBUILT_AVATARS.map((name) => <option key={name} value={name}>{name}</option>)}
          <option value="custom">{t("使用 Cloud Studio 中的其他形象", "Another avatar from Cloud Studio")}</option>
        </select>
      </label>
      {useCustomName && (
        <label>
          <span>{t("预置分身名称", "Prebuilt avatar name")}</span>
          <input value={voiceChat.voiceChatAvatarName} maxLength={80}
            onChange={(e) => voiceChat.onAvatarNameChange(e.target.value)}
            placeholder={t("填写 Cloud Studio 中的准确名称", "Exact name from Cloud Studio")} />
        </label>
      )}
      {useCustomName && <p className="vsAvatarPreferencesHint">
        {t("其他形象的名称须与 Google Cloud Studio 中的分身列表一致。", "Other avatar names must match the avatar list in Google Cloud Studio.")}
      </p>}
      <label>
        <span>{t("音色", "Voice")}</span>
        <select value={voiceChat.voiceChatVoice} onChange={(e) => voiceChat.onVoiceChange(e.target.value)}>
          {voiceChat.voiceChatVoiceOptions.map((voice) => (
            <option key={voice.value} value={voice.value}>{voice.label}</option>
          ))}
        </select>
      </label>
      <label>
        <span>{t("口音", "Accent")}</span>
        <select value={voiceChat.voiceChatAccent} onChange={(e) => voiceChat.onAccentChange(e.target.value)}>
          {GEMINI_LIVE_ACCENTS.map((accent) => (
            <option key={accent.value} value={accent.value}>{t(accent.zh, accent.en)}</option>
          ))}
        </select>
      </label>
      <p className="vsAvatarPreferencesHint">
        {t("口音由模型引导，效果可能变化；设置将在下次通话生效。", "Accent is guided and may vary. Settings apply to the next call.")}
      </p>
      <div className="vsAvatarPreferencesFooter">
        <button type="button" className="vsAvatarTextButton" onClick={() => {
          voiceChat.onAvatarEnabledChange(false);
          onDone();
        }}>{t("改为语音通话", "Switch to audio")}</button>
        <button type="button" className="vsAvatarDoneButton" disabled={!validName} onClick={onDone}>{t("完成", "Done")}</button>
      </div>
    </div>
  );
}
