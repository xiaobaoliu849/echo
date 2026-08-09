import { FormEvent, useEffect, useMemo, useState } from "react";
import { fetchSpeakAudio, fetchVoices, extractPdfText, polishPdfText, type TtsEngine, type VoiceInfo } from "../api";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import { formatVoiceLabel } from "../utils/voiceFormatter";

export type TtsWorkspaceMode = "text" | "dialogue" | "pdf";

function sortVoices(voices: VoiceInfo[], uiLanguage: UiLanguage): VoiceInfo[] {
  return [...voices].sort((a, b) => {
    const localeA = (a.locale || "").toLowerCase();
    const localeB = (b.locale || "").toLowerCase();

    const isZhA = localeA.startsWith("zh");
    const isZhB = localeB.startsWith("zh");
    const isEnA = localeA.startsWith("en");
    const isEnB = localeB.startsWith("en");

    if (uiLanguage === "zh-CN") {
      // Chinese first
      if (isZhA && !isZhB) return -1;
      if (!isZhA && isZhB) return 1;
      if (isZhA && isZhB) return a.name.localeCompare(b.name);

      // English second
      if (isEnA && !isEnB) return -1;
      if (!isEnA && isEnB) return 1;
      if (isEnA && isEnB) return a.name.localeCompare(b.name);
    } else {
      // English first
      if (isEnA && !isEnB) return -1;
      if (!isEnA && isEnB) return 1;
      if (isEnA && isEnB) return a.name.localeCompare(b.name);

      // Chinese second
      if (isZhA && !isZhB) return -1;
      if (!isZhA && isZhB) return 1;
      if (isZhA && isZhB) return a.name.localeCompare(b.name);
    }

    return a.locale.localeCompare(b.locale) || a.name.localeCompare(b.name);
  });
}

type Options = {
  defaultText: string;
  formatErrorMessage: FormatErrorMessage;
  language?: UiLanguage;
};

const DEFAULT_ENGINE_MODELS: Record<TtsEngine, { defaultModel: string; availableModels: string[] }> = {
  edge: { defaultModel: "", availableModels: [] },
  qwen_flash: {
    defaultModel: "qwen-audio-3.0-tts-flash",
    availableModels: ["qwen-audio-3.0-tts-flash", "qwen-audio-3.0-tts-plus", "qwen3-tts-flash-2025-11-27"]
  },
  minimax: {
    defaultModel: "speech-02-turbo",
    availableModels: ["speech-02-turbo", "speech-02-hd", "speech-01-turbo", "speech-01-hd"]
  },
  xiaomi: {
    defaultModel: "mimo-v2.5-tts",
    availableModels: ["mimo-v2.5-tts", "mimo-v2-tts"]
  },
  openai: {
    defaultModel: "tts-1",
    availableModels: ["tts-1", "tts-1-hd"]
  },
  elevenlabs: {
    defaultModel: "eleven_multilingual_v2",
    availableModels: ["eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_monolingual_v1"]
  },
  chattts: { defaultModel: "", availableModels: [] },
  gpt_sovits: { defaultModel: "", availableModels: [] },
  doubao: {
    defaultModel: "Doubao-语音合成-2.0",
    availableModels: ["Doubao-语音合成-2.0", "seed-tts-1.1"]
  },
};

export default function useTts({ defaultText, formatErrorMessage, language = "zh-CN" }: Options) {
  const t = createInlineTranslator(language);
  const [ttsMode, setTtsMode] = useState<TtsWorkspaceMode>("text");
  const [ttsEngine, setTtsEngine] = useState<TtsEngine>("edge");
  const [ttsEngineB, setTtsEngineB] = useState<TtsEngine>("edge");
  const [ttsModel, setTtsModel] = useState<string>("");
  const [ttsModelB, setTtsModelB] = useState<string>("");
  const [text, setText] = useState(defaultText);
  const [dialogueText, setDialogueText] = useState("");
  const [pdfText, setPdfText] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [voicesB, setVoicesB] = useState<VoiceInfo[]>([]);
  const [voice, setVoice] = useState("");
  const [voiceB, setVoiceB] = useState("");
  const [rate, setRate] = useState("+0%");
  const [audioUrl, setAudioUrl] = useState("");
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [loadingVoices, setLoadingVoices] = useState(true);
  const [loadingVoicesB, setLoadingVoicesB] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [extractingPdf, setExtractingPdf] = useState(false);
  const [polishingPdf, setPolishingPdf] = useState(false);
  const [ttsError, setTtsError] = useState("");
  const [ttsInfo, setTtsInfo] = useState("");

  useEffect(() => {
    let disposed = false;

    async function loadVoices() {
      try {
        setLoadingVoices(true);
        // Qwen TTS 的两个模型系列音色不通用，按当前模型过滤音色列表
        const effectiveModel = ttsModel || DEFAULT_ENGINE_MODELS[ttsEngine]?.defaultModel || "";
        const data = await fetchVoices(undefined, ttsEngine, effectiveModel || undefined);
        if (disposed) {
          return;
        }
        setVoices(data.voices);
        if (data.voices.length > 0) {
          // Set default voice as the first sorted voice for better UX
          const sorted = sortVoices(data.voices, language);
          setVoice(sorted[0].name);
        } else {
          setVoice("");
        }
      } catch (err) {
        if (!disposed) {
          setTtsError(formatErrorMessage(err, t("未知错误", "Unknown error.")));
        }
      } finally {
        if (!disposed) {
          setLoadingVoices(false);
        }
      }
    }

    void loadVoices();
    return () => {
      disposed = true;
    };
  }, [formatErrorMessage, ttsEngine, ttsModel, language]);

  useEffect(() => {
    let disposed = false;

    async function loadVoicesB() {
      try {
        setLoadingVoicesB(true);
        const effectiveModelB = ttsModelB || DEFAULT_ENGINE_MODELS[ttsEngineB]?.defaultModel || "";
        const data = await fetchVoices(undefined, ttsEngineB, effectiveModelB || undefined);
        if (disposed) {
          return;
        }
        setVoicesB(data.voices);
        if (data.voices.length > 0) {
          const sorted = sortVoices(data.voices, language);
          setVoiceB(sorted[0].name);
        } else {
          setVoiceB("");
        }
      } catch (err) {
        if (!disposed) {
          setTtsError(formatErrorMessage(err, t("未知错误", "Unknown error.")));
        }
      } finally {
        if (!disposed) {
          setLoadingVoicesB(false);
        }
      }
    }

    void loadVoicesB();
    return () => {
      disposed = true;
    };
  }, [formatErrorMessage, ttsEngineB, ttsModelB, language]);

  const voiceOptions = useMemo(() => {
    const sorted = sortVoices(voices, language);
    return sorted.map((item) => ({
      value: item.name,
      label: formatVoiceLabel(item, t)
    }));
  }, [voices, language, t]);

  const voiceOptionsB = useMemo(() => {
    const sorted = sortVoices(voicesB, language);
    return sorted.map((item) => ({
      value: item.name,
      label: formatVoiceLabel(item, t)
    }));
  }, [voicesB, language, t]);
  const engineOptions = useMemo(
    () => [
      { value: "edge" as TtsEngine, label: "Edge TTS", hint: t("系统级稳定合成，适合基础朗读。", "Stable system-level synthesis for standard narration.") },
      { value: "qwen_flash" as TtsEngine, label: "Qwen TTS (阿里云)", hint: t("阿里云 Qwen 音色，更适合中文与角色感。", "Alibaba Qwen voices, well suited to Chinese and stylized delivery.") },
      { value: "minimax" as TtsEngine, label: "MiniMax TTS", hint: t("MiniMax 多风格音色，适合配音与角色化朗读。", "MiniMax multi-style voices for dubbing and character reads.") },
      { value: "xiaomi" as TtsEngine, label: "Xiaomi TTS", hint: t("小米精品音色，支持唱歌模式与情感微调。", "Xiaomi high-quality voices, supporting singing mode and emotional nuances.") },
      { value: "openai" as TtsEngine, label: "OpenAI TTS", hint: t("OpenAI 拟真音色，合成效果极其自然逼真。", "OpenAI realistic voices with highly natural synthesis.") },
      { value: "elevenlabs" as TtsEngine, label: "ElevenLabs TTS", hint: t("ElevenLabs 顶尖音频合成，支持克隆及极高表现力音色。", "ElevenLabs top-tier voice synthesis, supports cloning and premium expression.") },
      { value: "chattts" as TtsEngine, label: "ChatTTS (本地)", hint: t("本地 ChatTTS 引擎，拟真度高，支持笑声和停顿。", "Local ChatTTS engine, highly realistic, supports laughter and breaths.") },
      { value: "gpt_sovits" as TtsEngine, label: "GPT-SoVITS (本地)", hint: t("本地 GPT-SoVITS API，支持高质量个性化声音克隆。", "Local GPT-SoVITS API, supports high-quality personalized voice cloning.") },
      { value: "doubao" as TtsEngine, label: "豆包 TTS (火山引擎)", hint: t("火山引擎豆包语音合成，支持大模型音色、情感控制与流式合成。", "Volcengine Doubao TTS with large-model voices, emotion control and streaming synthesis.") },
    ],
    [t]
  );

  const activeSourceText = useMemo(() => {
    if (ttsMode === "dialogue") {
      return dialogueText.trim();
    }
    if (ttsMode === "pdf") {
      return pdfText.trim();
    }
    return text.trim();
  }, [dialogueText, pdfText, text, ttsMode]);

  useEffect(() => {
    return () => {
      if (audioUrl.startsWith("blob:")) {
        URL.revokeObjectURL(audioUrl);
      }
    };
  }, [audioUrl]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setTtsError("");
    setTtsInfo("");
    if (!activeSourceText) {
      if (ttsMode === "dialogue") {
        setTtsError(t("请输入要合成的对话脚本。", "Enter a dialogue script to synthesize."));
        return;
      }
      if (ttsMode === "pdf") {
        setTtsError(t("请先选择 PDF 并准备可朗读文本。", "Choose a PDF first and prepare readable text."));
        return;
      }
      setTtsError(t("请输入要合成的文本。", "Enter text to synthesize."));
      return;
    }
    setGenerating(true);
    try {
      const result = await fetchSpeakAudio({
        text: activeSourceText,
        voice: voice || undefined,
        voiceB: ttsMode === "dialogue" ? (voiceB || undefined) : undefined,
        rate,
        engine: ttsEngine,
        engineB: ttsMode === "dialogue" ? ttsEngineB : undefined,
        model: ttsModel || undefined,
        modelB: ttsMode === "dialogue" ? (ttsModelB || undefined) : undefined,
      });
      if (audioUrl.startsWith("blob:")) {
        URL.revokeObjectURL(audioUrl);
      }
      setAudioBlob(result.blob);
      setAudioUrl(URL.createObjectURL(result.blob));
      if (result.memorySaved) {
        setTtsInfo(t("已将本次语音生成偏好写入长期记忆。", "Saved this voice generation preference into long-term memory."));
      }
    } catch (err) {
      setTtsError(formatErrorMessage(err, t("语音合成请求失败。", "Text-to-speech request failed.")));
    } finally {
      setGenerating(false);
    }
  }

  function onTtsModeChange(mode: TtsWorkspaceMode) {
    setTtsMode(mode);
    setTtsError("");
    setTtsInfo("");
  }

  function onEngineChange(engine: TtsEngine) {
    setTtsEngine(engine);
    setTtsModel(DEFAULT_ENGINE_MODELS[engine]?.defaultModel || "");
    setTtsError("");
    setTtsInfo("");
    if (audioUrl.startsWith("blob:")) {
      URL.revokeObjectURL(audioUrl);
    }
    setAudioBlob(null);
    setAudioUrl("");
  }

  function onEngineBChange(engine: TtsEngine) {
    setTtsEngineB(engine);
    setTtsModelB(DEFAULT_ENGINE_MODELS[engine]?.defaultModel || "");
    setTtsError("");
    setTtsInfo("");
    if (audioUrl.startsWith("blob:")) {
      URL.revokeObjectURL(audioUrl);
    }
    setAudioBlob(null);
    setAudioUrl("");
  }

  function onTextChange(value: string) {
    setText(value);
    if (ttsMode === "text" && ttsError) {
      setTtsError("");
    }
  }

  function onDialogueTextChange(value: string) {
    setDialogueText(value);
    if (ttsMode === "dialogue" && ttsError) {
      setTtsError("");
    }
  }

  async function onPdfFileChange(file: File | null) {
    setPdfFile(file);
    if (!file) {
      setPdfText("");
      setTtsInfo("");
      return;
    }
    if (ttsMode === "pdf" && ttsError) {
      setTtsError("");
    }

    try {
      setExtractingPdf(true);
      setTtsInfo(t("正在从 PDF 中提取文本...", "Extracting text from PDF..."));
      const res = await extractPdfText(file);
      setPdfText(res.text);
      setTtsInfo(
        t(
          `成功从 PDF 提取了 ${res.page_count} 页文本。`,
          `Successfully extracted text from ${res.page_count} pages of PDF.`
        )
      );
    } catch (err) {
      setTtsError(formatErrorMessage(err, t("PDF 文本提取失败", "Failed to extract text from PDF.")));
      setTtsInfo("");
    } finally {
      setExtractingPdf(false);
    }
  }

  function onPdfTextChange(value: string) {
    setPdfText(value);
    if (ttsMode === "pdf" && ttsError) {
      setTtsError("");
    }
  }

  async function onPolishPdfText() {
    if (!pdfText.trim()) return;
    try {
      setPolishingPdf(true);
      setTtsInfo(t("正在使用 AI 整理并优化朗读文本...", "AI is organizing and optimizing text for TTS..."));
      const res = await polishPdfText(pdfText);
      setPdfText(res.polished_text);
      setTtsInfo(t("AI 朗读优化完成！已移除符号、页码并转译数学公式。", "AI optimization complete! Removed symbols, page numbers, and translated formulas."));
    } catch (err) {
      setTtsError(formatErrorMessage(err, t("AI 朗读优化失败", "Failed to optimize text with AI.")));
      setTtsInfo("");
    } finally {
      setPolishingPdf(false);
    }
  }

  const ttsModelOptions = useMemo(() => {
    const defaultList = DEFAULT_ENGINE_MODELS[ttsEngine]?.availableModels || [];
    if (ttsModel && !defaultList.includes(ttsModel)) {
      return [...defaultList, ttsModel];
    }
    return defaultList;
  }, [ttsEngine, ttsModel]);

  const ttsModelOptionsB = useMemo(() => {
    const defaultList = DEFAULT_ENGINE_MODELS[ttsEngineB]?.availableModels || [];
    if (ttsModelB && !defaultList.includes(ttsModelB)) {
      return [...defaultList, ttsModelB];
    }
    return defaultList;
  }, [ttsEngineB, ttsModelB]);

  return {
    ttsMode,
    ttsEngine,
    ttsEngineB,
    ttsModel,
    ttsModelB,
    text,
    dialogueText,
    pdfText,
    pdfFile,
    voices,
    voicesB,
    voice,
    voiceB,
    rate,
    audioUrl,
    audioBlob,
    loadingVoices,
    loadingVoicesB,
    generating,
    extractingPdf,
    polishingPdf,
    ttsError,
    ttsInfo,
    engineOptions,
    voiceOptions,
    voiceOptionsB,
    ttsModelOptions,
    ttsModelOptionsB,
    activeSourceText,
    onSubmit,
    onTtsModeChange,
    onEngineChange,
    onEngineBChange,
    onModelChange: setTtsModel,
    onModelBChange: setTtsModelB,
    onTextChange,
    onDialogueTextChange,
    onPdfFileChange,
    onPdfTextChange,
    onPolishPdfText,
    onVoiceChange: setVoice,
    onVoiceBChange: setVoiceB,
    onRateChange: setRate
  };

}

export type UseTtsResult = ReturnType<typeof useTts>;
