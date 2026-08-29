import { FormEvent, useEffect, useState } from "react";
import {
  createVoiceClone,
  createVoiceDesign,
  deleteCustomVoice,
  listCustomVoices,
  type CustomVoice,
  type VoiceType
} from "../api";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";

type Options = {
  formatErrorMessage: FormatErrorMessage;
  language?: UiLanguage;
  dashscopeApiKeyConfigured?: boolean;
  xiaomiApiKeyConfigured?: boolean;
};

const CLONE_ACCEPTED_TYPES = [
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/flac",
  "audio/x-flac",
  "audio/mp4",
  "audio/aac",
  "audio/ogg",
  "audio/webm"
];

const MAX_CLONE_FILE_BYTES = 20 * 1024 * 1024;

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function useVoiceManagement({
  formatErrorMessage,
  language = "zh-CN",
  dashscopeApiKeyConfigured = false,
  xiaomiApiKeyConfigured = false,
}: Options) {
  const [voiceProvider, setVoiceProvider] = useState<"qwen" | "xiaomi" | "gpt_sovits">("qwen");
  const t = createInlineTranslator(language);
  const designPromptPresets = [
    {
      id: "warm_narrator",
      label: t("温暖旁白", "Warm Narrator"),
      prompt: t(
        "温暖、亲和、清晰，适合知识讲解、播客开场和故事叙述。",
        "Warm, approachable, and clear. Suitable for explainers, podcast intros, and storytelling."
      )
    },
    {
      id: "professional_host",
      label: t("专业主持", "Professional Host"),
      prompt: t(
        "专业、稳重、节奏清楚，适合访谈主持、品牌介绍和正式播报。",
        "Professional, steady, and well paced. Suitable for interviews, brand intros, and formal delivery."
      )
    },
    {
      id: "youthful_social",
      label: t("轻快社媒", "Social & Light"),
      prompt: t(
        "年轻、自然、轻快，适合短视频口播、产品安利和生活方式内容。",
        "Young, natural, and upbeat. Suitable for short videos, product promos, and lifestyle content."
      )
    }
  ];
  const [designPrompt, setDesignPrompt] = useState(
    t("温柔、清晰、语速适中，适合讲解和对话。", "Gentle, clear, and moderately paced for explainers and dialogue.")
  );
  const [designPreviewText, setDesignPreviewText] = useState(
    t(
      "你好，我是 Echo 新创建的音色，很高兴为你服务。",
      "Hello, I am a new voice created with Echo. Glad to speak with you."
    )
  );
  const [designName, setDesignName] = useState("voice_design_demo");
  const [designLanguage, setDesignLanguage] = useState("zh");
  const [designBusy, setDesignBusy] = useState(false);
  const [designListBusy, setDesignListBusy] = useState(false);
  const [designError, setDesignError] = useState("");
  const [designInfo, setDesignInfo] = useState("");
  const [designPreviewAudio, setDesignPreviewAudio] = useState("");
  const [designVoices, setDesignVoices] = useState<CustomVoice[]>([]);

  const [cloneName, setCloneName] = useState("voice_clone_demo");
  const [cloneAudioFile, setCloneAudioFile] = useState<File | null>(null);
  const [cloneBusy, setCloneBusy] = useState(false);
  const [cloneListBusy, setCloneListBusy] = useState(false);
  const [cloneError, setCloneError] = useState("");
  const [cloneInfo, setCloneInfo] = useState("");
  const [cloneVoices, setCloneVoices] = useState<CustomVoice[]>([]);

  function setMissingKeyError(voiceType: VoiceType) {
    const isXiaomi = voiceProvider === "xiaomi";
    const message = isXiaomi
      ? t(
          "请先在设置中配置小米 API Key，再使用音色设计/克隆。",
          "Configure the Xiaomi API Key in Settings before using voice design/clone."
        )
      : t(
          "请先在设置中配置 DashScope API Key，再使用音色设计/克隆。",
          "Configure the DashScope API Key in Settings before using voice design/clone."
        );
    if (voiceType === "voice_design") {
      setDesignError(message);
    } else {
      setCloneError(message);
    }
  }

  function isCurrentProviderKeyConfigured(): boolean {
    if (voiceProvider === "gpt_sovits") return true;
    return voiceProvider === "xiaomi" ? xiaomiApiKeyConfigured : dashscopeApiKeyConfigured;
  }

  async function refreshCustomVoices(voiceType: VoiceType, options: { silentIfMissingKey?: boolean } = {}) {
    if (!isCurrentProviderKeyConfigured()) {
      if (!options.silentIfMissingKey) {
        setMissingKeyError(voiceType);
      }
      return;
    }
    try {
      if (voiceType === "voice_design") {
        setDesignListBusy(true);
      } else {
        setCloneListBusy(true);
      }
      const result = await listCustomVoices(voiceType, voiceProvider);
      if (voiceType === "voice_design") {
        setDesignVoices(result.voices);
      } else {
        setCloneVoices(result.voices);
      }
    } catch (err) {
      const message = formatErrorMessage(err, t("加载音色列表失败。", "Failed to load the voice list."));
      if (voiceType === "voice_design") {
        setDesignError(message);
      } else {
        setCloneError(message);
      }
    } finally {
      if (voiceType === "voice_design") {
        setDesignListBusy(false);
      } else {
        setCloneListBusy(false);
      }
    }
  }

  useEffect(() => {
    void refreshCustomVoices("voice_design", { silentIfMissingKey: true });
    void refreshCustomVoices("voice_clone", { silentIfMissingKey: true });
  }, [dashscopeApiKeyConfigured, xiaomiApiKeyConfigured, voiceProvider]);

  async function onDesignSubmit(event: FormEvent) {
    event.preventDefault();
    setDesignError("");
    setDesignInfo("");
    if (!designName.trim()) {
      setDesignError(t("请先填写音色名称。", "Enter a voice name first."));
      return;
    }
    if (designPrompt.trim().length < 10) {
      setDesignError(t("请提供更具体的音色描述，至少 10 个字。", "Provide a more specific voice description with at least 10 characters."));
      return;
    }
    if (designPreviewText.trim().length < 6) {
      setDesignError(t("请填写足够长的试听文本，方便判断音色效果。", "Enter a longer preview text so the voice quality can be judged."));
      return;
    }
    if (!isCurrentProviderKeyConfigured()) {
      setMissingKeyError("voice_design");
      return;
    }
    setDesignBusy(true);
    try {
      const result = await createVoiceDesign({
        voice_prompt: designPrompt.trim(),
        preview_text: designPreviewText.trim(),
        preferred_name: designName.trim(),
        language: designLanguage.trim() || "zh",
        provider: voiceProvider,
      });
      setDesignInfo(t(`已创建音色：${result.voice ?? "未知"}`, `Created voice: ${result.voice ?? "unknown"}`));
      const previewAudioData = result.preview_audio_data || "";
      setDesignPreviewAudio(
        previewAudioData ? `data:audio/wav;base64,${previewAudioData}` : ""
      );
      await refreshCustomVoices("voice_design");
    } catch (err) {
      setDesignError(formatErrorMessage(err, t("创建音色设计失败。", "Failed to create the designed voice.")));
    } finally {
      setDesignBusy(false);
    }
  }

  async function onCloneSubmit(event: FormEvent) {
    event.preventDefault();
    setCloneError("");
    setCloneInfo("");
    if (!cloneName.trim()) {
      setCloneError(t("请先填写克隆音色名称。", "Enter a cloned voice name first."));
      return;
    }
    if (!cloneAudioFile) {
      setCloneError(t("请先选择音频文件。", "Choose an audio file first."));
      return;
    }
    if (!isCurrentProviderKeyConfigured()) {
      setMissingKeyError("voice_clone");
      return;
    }
    setCloneBusy(true);
    try {
      const result = await createVoiceClone({
        preferred_name: cloneName.trim(),
        audio_file: cloneAudioFile,
        provider: voiceProvider,
      });
      setCloneInfo(t(`已创建音色：${result.voice ?? "未知"}`, `Created voice: ${result.voice ?? "unknown"}`));
      await refreshCustomVoices("voice_clone");
    } catch (err) {
      setCloneError(formatErrorMessage(err, t("创建克隆音色失败。", "Failed to create the cloned voice.")));
    } finally {
      setCloneBusy(false);
    }
  }

  async function onDeleteVoice(voiceName: string, voiceType: VoiceType) {
    try {
      await deleteCustomVoice(voiceName, voiceType, voiceProvider);
      await refreshCustomVoices(voiceType);
    } catch (err) {
      const message = formatErrorMessage(err, t("删除音色失败。", "Failed to delete the voice."));
      if (voiceType === "voice_design") {
        setDesignError(message);
      } else {
        setCloneError(message);
      }
    }
  }

  function onApplyDesignPreset(prompt: string) {
    setDesignPrompt(prompt);
    setDesignError("");
    setDesignInfo(t("已应用音色描述预设。", "Applied the voice prompt preset."));
  }

  function onCloneAudioFileChange(file: File | null) {
    setCloneAudioFile(file);
    setCloneError("");
    if (!file) {
      return;
    }
    if (file.size > MAX_CLONE_FILE_BYTES) {
      setCloneError(t("音频文件过大，建议控制在 20MB 以内。", "The audio file is too large. Keep it within 20MB."));
      return;
    }
    if (file.type && !CLONE_ACCEPTED_TYPES.includes(file.type)) {
      setCloneError(
        t(
          "暂不支持该音频格式，请使用 mp3、wav、flac、m4a、ogg 或 webm。",
          "This audio format is not supported yet. Use mp3, wav, flac, m4a, ogg, or webm."
        )
      );
      return;
    }
    setCloneInfo(t(`已载入样本：${file.name} (${formatBytes(file.size)})`, `Loaded sample: ${file.name} (${formatBytes(file.size)})`));
  }

  const designCanSubmit =
    !designBusy &&
    designName.trim().length > 0 &&
    designPrompt.trim().length >= 10 &&
    designPreviewText.trim().length >= 6;

  const cloneCanSubmit =
    !cloneBusy &&
    cloneName.trim().length > 0 &&
    cloneAudioFile !== null &&
    cloneAudioFile.size <= MAX_CLONE_FILE_BYTES &&
    (!cloneAudioFile.type || CLONE_ACCEPTED_TYPES.includes(cloneAudioFile.type));

  const cloneFileSummary = cloneAudioFile
    ? `${cloneAudioFile.name} · ${formatBytes(cloneAudioFile.size)}`
    : "";

  return {
    voiceProvider,
    setVoiceProvider,
    design: {
      designPrompt,
      designPreviewText,
      designName,
      designLanguage,
      designBusy,
      designListBusy,
      designError,
      designInfo,
      designPreviewAudio,
      designVoices,
      designCanSubmit,
      designPromptPresets,
      designGuidelines: [
        t("描述音色的人设、语气、节奏和使用场景。", "Describe the persona, tone, pacing, and target usage."),
        t("试听文本最好覆盖陈述句、疑问句和情绪起伏。", "Preview text should cover statements, questions, and emotional changes."),
        t("先做 2 到 3 个方向，再挑最接近产品场景的音色。", "Try 2 to 3 directions first, then pick the one closest to your product need.")
      ],
      onSubmit: onDesignSubmit,
      onRefresh: () => refreshCustomVoices("voice_design"),
      onDeleteVoice: (voiceName: string) => onDeleteVoice(voiceName, "voice_design"),
      onPromptChange: setDesignPrompt,
      onPreviewTextChange: setDesignPreviewText,
      onNameChange: setDesignName,
      onLanguageChange: setDesignLanguage,
      onApplyPreset: onApplyDesignPreset
    },
    clone: {
      cloneName,
      cloneAudioFile,
      cloneBusy,
      cloneListBusy,
      cloneError,
      cloneInfo,
      cloneVoices,
      cloneCanSubmit,
      cloneFileSummary,
      cloneAcceptedFormats: ["mp3", "wav", "flac", "m4a", "ogg", "webm"],
      cloneRequirements: [
        t("建议 10 到 30 秒的干净人声，不要混背景音乐。", "Use 10 to 30 seconds of clean voice audio without background music."),
        t("尽量单人说话，避免重叠和混响。", "Prefer a single speaker and avoid overlap or reverb."),
        t("录音音量稳定，语句完整，采样清晰。", "Keep the recording level stable, sentences complete, and the sample clear.")
      ],
      onSubmit: onCloneSubmit,
      onRefresh: () => refreshCustomVoices("voice_clone"),
      onDeleteVoice: (voiceName: string) => onDeleteVoice(voiceName, "voice_clone"),
      onNameChange: setCloneName,
      onAudioFileChange: onCloneAudioFileChange
    }
  };
}

export type UseVoiceManagementResult = ReturnType<typeof useVoiceManagement>;
export type VoiceDesignController = UseVoiceManagementResult["design"];
export type VoiceCloneController = UseVoiceManagementResult["clone"];
