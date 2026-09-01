import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  clearPersistedEverMemConversationGroupId,
  ensureEverMemConversationGroupId,
  getPersistedEverMemConversationGroupId,
  persistEverMemConversationGroupId,
  streamChatCompletion,
  type ChatMessage,
  type ChatAttachment,
} from "../api";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import { createMessageId, ensureMessageIds } from "../utils/messageId";
import { resolveRealtimeModelOptions } from "./useVoiceChatHelpers";

type Options = {
  formatErrorMessage: FormatErrorMessage;
  providerOptions?: string[];
  providerModelCatalog?: Record<
    string,
    {
      defaultModel: string;
      availableModels: string[];
      enabledModels?: string[];
    }
  >;
  preferredProvider?: string;
  language?: UiLanguage;
};

type ChatModelChoice = {
  provider: string;
  model: string;
  label: string;
  value: string;
};

const MODEL_CHOICE_SEPARATOR = "\u001f";
export function isVoiceRealtimeModel(provider: string, model: string): boolean {
  const normalizedProvider = (provider || "").trim().toLowerCase();
  const normalizedModel = (model || "").trim().toLowerCase();
  if (!normalizedModel) {
    return false;
  }
  if (
    normalizedProvider === "personaplex" ||
    normalizedProvider === "glm4voice" ||
    normalizedProvider === "tavus" ||
    normalizedProvider === "cartesia" ||
    normalizedProvider === "gradium"
  ) {
    return true;
  }
  if (normalizedProvider === "dashscope") {
    return normalizedModel.includes("realtime") || normalizedModel.includes("livetranslate");
  }
  if (normalizedProvider === "google") {
    return (
      normalizedModel.includes("native-audio") ||
      normalizedModel.includes("live") ||
      normalizedModel.includes("realtime")
    );
  }
  return normalizedModel.includes("realtime");
}

/**
 * Short capability badge shown next to a model name in the picker flyouts.
 * Returns "" for plain text models; shared by ChatModelSelect and
 * VoiceCallSettingsPopover so the labels never drift apart.
 */
export function formatModelHint(provider: string, model: string, t: (zh: string, en: string) => string): string {
  if (!isVoiceRealtimeModel(provider, model)) {
    return "";
  }
  const normalizedProv = (provider || "").trim().toLowerCase();
  if (normalizedProv === "tavus" || model.toLowerCase().includes("tavus")) {
    return t("实时视频分身", "Video PAL avatar");
  }
  if (normalizedProv === "cartesia" || model.toLowerCase().includes("cartesia")) {
    return t("Cartesia 极速语音", "Cartesia Sonic Voice");
  }
  if (normalizedProv === "gradium" || model.toLowerCase().includes("gradium")) {
    return t("Gradium 实时语音", "Gradium Voice AI");
  }
  if (normalizedProv === "glm4voice" || model.toLowerCase().includes("glm-4-voice")) {
    return t("智谱端到端语音", "GLM-4-Voice bilingual");
  }
  if (normalizedProv === "personaplex" || model.toLowerCase().includes("personaplex")) {
    return t("NVIDIA 全双工陪练", "NVIDIA duplex call");
  }
  const normalized = model.toLowerCase();
  if (normalized.includes("live-translate") || normalized.includes("livetranslate")) {
    return t("实时翻译", "Live translate");
  }
  if (normalized.includes("qwen-audio")) {
    return t("Qwen-Audio 原生实时", "Qwen-Audio native");
  }
  if (normalized.includes("omni")) {
    return t("全模态实时", "Omni realtime");
  }
  return t("实时通话", "Realtime call");
}

export function buildModelChoiceValue(provider: string, model: string): string {
  return `${provider}${MODEL_CHOICE_SEPARATOR}${model}`;
}

function parseModelChoiceValue(value: string): { provider: string; model: string } | null {
  const separatorIndex = value.indexOf(MODEL_CHOICE_SEPARATOR);
  if (separatorIndex < 0) {
    return null;
  }
  const provider = value.slice(0, separatorIndex).trim();
  const model = value.slice(separatorIndex + MODEL_CHOICE_SEPARATOR.length).trim();
  if (!provider || !model) {
    return null;
  }
  return { provider, model };
}

function resolveProvider(
  preferredProvider: string | undefined,
  providerOptions: string[],
): string {
  if (preferredProvider && providerOptions.includes(preferredProvider)) {
    return preferredProvider;
  }
  if (providerOptions.length > 0) {
    return providerOptions[0];
  }
  return "Google";
}

function resolveDefaultModel(
  provider: string,
  providerModelCatalog: Options["providerModelCatalog"],
): string {
  const providerMeta = providerModelCatalog?.[provider];
  if (!providerMeta) {
    return "";
  }
  const enabledModels = Array.isArray(providerMeta.enabledModels)
    ? providerMeta.enabledModels.filter((item) => item.trim())
    : [];
  const rawAvailable = Array.isArray(providerMeta.availableModels)
    ? providerMeta.availableModels.filter((item) => item.trim())
    : [];
  const preferredDefault = (providerMeta.defaultModel || "").trim();

  let availableModels = enabledModels.length > 0 ? enabledModels : rawAvailable;
  if (preferredDefault && !availableModels.includes(preferredDefault)) {
    availableModels = [preferredDefault, ...availableModels];
  }

  const textModels = availableModels.filter((item) => !isVoiceRealtimeModel(provider, item));

  if (preferredDefault && !isVoiceRealtimeModel(provider, preferredDefault)) {
    return preferredDefault;
  }
  if (textModels.length > 0) {
    return textModels[0] || "";
  }
  return preferredDefault || availableModels[0] || "";
}

function resolveModelOptions(
  provider: string,
  providerModelCatalog: Options["providerModelCatalog"],
): string[] {
  const providerMeta = providerModelCatalog?.[provider];
  if (!providerMeta) {
    return resolveRealtimeModelOptions(provider, {});
  }
  const enabledModels = Array.isArray(providerMeta.enabledModels)
    ? providerMeta.enabledModels.filter((item) => item.trim())
    : [];
  const rawAvailable = Array.isArray(providerMeta.availableModels)
    ? providerMeta.availableModels.filter((item) => item.trim())
    : [];
  const preferredDefault = (providerMeta.defaultModel || "").trim();

  let availableModels = enabledModels.length > 0 ? enabledModels : rawAvailable;
  if (preferredDefault && !availableModels.includes(preferredDefault)) {
    availableModels = [preferredDefault, ...availableModels];
  }

  if (availableModels.length > 0) {
    return [...new Set(availableModels.map((item) => item.trim()).filter(Boolean))];
  }

  const realtimeModels = resolveRealtimeModelOptions(provider, providerModelCatalog || {});
  const combined = [...availableModels, ...realtimeModels]
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set(combined)];
}

function resolveAllModelChoices(
  providerOptions: string[],
  providerModelCatalog: Options["providerModelCatalog"],
): ChatModelChoice[] {
  const providers = [
    ...providerOptions,
    ...Object.keys(providerModelCatalog || {}).filter((provider) => !providerOptions.includes(provider)),
  ];

  return providers.flatMap((provider) => {
    return resolveModelOptions(provider, providerModelCatalog).map((model) => ({
      provider,
      model,
      label: `${provider} / ${model}`,
      value: buildModelChoiceValue(provider, model),
    }));
  });
}

export default function useChat({
  formatErrorMessage,
  providerOptions = [],
  providerModelCatalog = {},
  preferredProvider,
  language = "zh-CN",
}: Options) {
  const t = createInlineTranslator(language);
  const initialProvider = resolveProvider(preferredProvider, providerOptions);
  const [chatProvider, setChatProvider] = useState(initialProvider);
  const [chatModel, setChatModel] = useState(
    resolveDefaultModel(initialProvider, providerModelCatalog)
  );
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState("");
  const [chatMemoryGroupId, setChatMemoryGroupId] = useState(() => getPersistedEverMemConversationGroupId("chat"));
  const [useMemory, setUseMemory] = useState(true);
  const [deepThinking, setDeepThinking] = useState(false);
  const [chatAttachments, setChatAttachments] = useState<ChatAttachment[]>([]);
  const lastPreferredProviderRef = useRef(preferredProvider);
  const streamAbortRef = useRef<AbortController | null>(null);

  function abortActiveStream() {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
      streamAbortRef.current = null;
    }
  }

  function addChatAttachment(nameOrAttachment: string | ChatAttachment, content?: string) {
    if (typeof nameOrAttachment === "object") {
      setChatAttachments((prev) => [...prev, nameOrAttachment]);
    } else {
      setChatAttachments((prev) => [...prev, { name: nameOrAttachment, content: content || "" }]);
    }
  }

  function removeChatAttachment(index: number) {
    setChatAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  function clearChatAttachments() {
    setChatAttachments([]);
  }

  const chatProviderOptions = useMemo(
    () => (providerOptions.length > 0 ? providerOptions : ["Google"]),
    [providerOptions],
  );
  const chatModelOptions = useMemo(
    () => resolveModelOptions(chatProvider, providerModelCatalog),
    [chatProvider, providerModelCatalog],
  );
  const chatModelChoices = useMemo(
    () => resolveAllModelChoices(chatProviderOptions, providerModelCatalog),
    [chatProviderOptions, providerModelCatalog],
  );
  const chatModelChoiceValue = chatModel.trim()
    ? buildModelChoiceValue(chatProvider, chatModel.trim())
    : "";

  useEffect(() => {
    const preferredProviderChanged = lastPreferredProviderRef.current !== preferredProvider;
    lastPreferredProviderRef.current = preferredProvider;

    const nextProvider = resolveProvider(preferredProvider, chatProviderOptions);
    if (preferredProviderChanged && chatProvider !== nextProvider) {
      setChatProvider(nextProvider);
      setChatModel(resolveDefaultModel(nextProvider, providerModelCatalog));
      return;
    }

    if (!chatProviderOptions.includes(chatProvider)) {
      setChatProvider(nextProvider);
      setChatModel(resolveDefaultModel(nextProvider, providerModelCatalog));
      return;
    }

    const defaultModel = resolveDefaultModel(chatProvider, providerModelCatalog);
    const hasOptions = chatModelOptions.length > 0;
    const currentModelStillValid =
      !hasOptions ||
      !chatModel.trim() ||
      chatModelOptions.includes(chatModel.trim()) ||
      isVoiceRealtimeModel(chatProvider, chatModel.trim());

    if (!chatModel.trim() || !currentModelStillValid) {
      setChatModel(defaultModel);
    }
  }, [
    chatModel,
    chatModelOptions,
    chatProvider,
    chatProviderOptions,
    preferredProvider,
    providerModelCatalog,
  ]);

  function onProviderChange(nextProvider: string) {
    setChatProvider(nextProvider);
    setChatModel(resolveDefaultModel(nextProvider, providerModelCatalog));
  }

  function onModelChoiceChange(value: string) {
    const choice = parseModelChoiceValue(value);
    if (!choice) {
      setChatModel(value);
      return;
    }
    setChatProvider(choice.provider);
    setChatModel(choice.model);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const userText = chatInput.trim();
    if (!userText) {
      return;
    }
    if (isVoiceRealtimeModel(chatProvider, chatModel)) {
      setChatError(t(
        "当前选择的是实时语音/实时翻译模型，请点击实时通话按钮开始语音会话，或切换到普通文本模型后再发送文字。",
        "The selected model is realtime voice/live translation only. Start a realtime call, or switch to a text model before sending text."
      ));
      return;
    }
    setChatError("");
    setChatBusy(true);

    let finalContent = userText;
    if (chatAttachments.length > 0) {
      const formattedAttachments = chatAttachments.map(
        (att) => `[Attachment File: ${att.name}]\n---\n${att.content}\n---\n`
      ).join("\n\n");
      finalContent = `${formattedAttachments}\n${userText}`;
    }

    const nextHistory: ChatMessage[] = [
      ...chatMessages,
      { role: "user", content: userText, attachments: [...chatAttachments], id: createMessageId() }
    ];

    const apiHistory: ChatMessage[] = [
      ...chatMessages,
      { role: "user", content: finalContent }
    ];

    setChatMessages([...nextHistory, { role: "assistant", content: "", id: createMessageId() }]);
    setChatInput("");
    setChatAttachments([]);

    abortActiveStream();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      let memoryGroupId = "";
      try {
        memoryGroupId = await ensureEverMemConversationGroupId("chat", chatMemoryGroupId);
        if (memoryGroupId && memoryGroupId !== chatMemoryGroupId) {
          const persisted = persistEverMemConversationGroupId("chat", memoryGroupId);
          setChatMemoryGroupId(persisted);
        }
      } catch {
        memoryGroupId = "";
      }

      let streamedReply = "";
      let streamedReasoning = "";
      await streamChatCompletion(
        {
          provider: chatProvider,
          model: chatModel.trim() || undefined,
          messages: apiHistory,
          temperature: 0.7,
          max_tokens: 1024,
          use_memory: useMemory,
          deep_thinking: deepThinking
        },
        {
          onDelta: (chunk) => {
            streamedReply += chunk;
            setChatMessages((prev) => {
              if (!prev.length) {
                return prev;
              }
              const next = [...prev];
              const lastIdx = next.length - 1;
              const last = next[lastIdx];
              if (last.role !== "assistant") {
                return prev;
              }
              next[lastIdx] = { ...last, content: streamedReply };
              return next;
            });
          },
          onReasoning: (chunk) => {
            streamedReasoning += chunk;
            setChatMessages((prev) => {
              if (!prev.length) {
                return prev;
              }
              const next = [...prev];
              const lastIdx = next.length - 1;
              const last = next[lastIdx];
              if (last.role !== "assistant") {
                return prev;
              }
              next[lastIdx] = { ...last, reasoningContent: streamedReasoning };
              return next;
            });
          },
          onDone: (meta) => {
            if (meta?.memoriesRetrieved || meta?.memorySaved) {
              setChatMessages((prev) => {
                const next = [...prev];
                const lastIdx = next.length - 1;
                const prevIdx = lastIdx - 1;

                if (meta.memorySaved && prevIdx >= 0 && next[prevIdx].role === "user") {
                  next[prevIdx] = { ...next[prevIdx], memorySaved: true };
                }
                if (meta.memoriesRetrieved && lastIdx >= 0 && next[lastIdx].role === "assistant") {
                  next[lastIdx] = { ...next[lastIdx], memoriesUsed: meta.memoriesRetrieved };
                }
                return next;
              });
            }
          }
        },
        {
          memoryGroupId: memoryGroupId || undefined,
          signal: controller.signal,
        }
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      setChatMessages((prev) => {
        if (!prev.length) {
          return prev;
        }
        const last = prev[prev.length - 1];
        if (last.role === "assistant" && !last.content.trim()) {
          return prev.slice(0, -1);
        }
        return prev;
      });
      setChatError(formatErrorMessage(err, t("聊天请求失败。", "Chat request failed.")));
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
        setChatBusy(false);
      }
    }
  }

  function onNewSession() {
    abortActiveStream();
    setChatMessages([]);
    setChatInput("");
    setChatError("");
    setChatBusy(false);
    setChatAttachments([]);
    clearPersistedEverMemConversationGroupId("chat");
    setChatMemoryGroupId("");
  }

  function replaceSession(messages: ChatMessage[], memoryGroupId = "") {
    abortActiveStream();
    const normalizedGroupId = (memoryGroupId || "").trim();
    setChatMessages(Array.isArray(messages) ? ensureMessageIds(messages) : []);
    setChatInput("");
    setChatError("");
    setChatBusy(false);
    setChatAttachments([]);
    if (normalizedGroupId) {
      setChatMemoryGroupId(persistEverMemConversationGroupId("chat", normalizedGroupId));
    } else {
      clearPersistedEverMemConversationGroupId("chat");
      setChatMemoryGroupId("");
    }
  }

  function injectMessage(role: "user" | "assistant", content: string) {
    if (!content.trim()) return;
    setChatMessages((prev) => [...prev, { role, content, id: createMessageId() }]);
  }

  function deleteMessage(index: number) {
    setChatMessages((prev) => prev.filter((_, i) => i !== index));
  }

  async function regenerateMessage(index: number) {
    if (chatBusy) return;
    const msg = chatMessages[index];
    if (!msg || msg.role !== "assistant") return;

    // Get the messages list up to this assistant message
    const historyBefore = chatMessages.slice(0, index);
    // Find the last user message in that history
    const lastUserIdx = historyBefore.map(m => m.role).lastIndexOf("user");
    if (lastUserIdx < 0) return;

    setChatError("");
    setChatBusy(true);

    // Re-slice the messages up to the user message
    const nextHistory = chatMessages.slice(0, lastUserIdx + 1);
    const userMsg = nextHistory[nextHistory.length - 1];
    let finalContent = userMsg.content;
    if (userMsg.attachments && userMsg.attachments.length > 0) {
      const formattedAttachments = userMsg.attachments.map(
        (att) => `[Attachment File: ${att.name}]\n---\n${att.content}\n---\n`
      ).join("\n\n");
      finalContent = `${formattedAttachments}\n${userMsg.content}`;
    }
    const apiHistory: ChatMessage[] = [
      ...nextHistory.slice(0, -1),
      { role: "user" as const, content: finalContent }
    ];

    setChatMessages([...nextHistory, { role: "assistant", content: "", id: createMessageId() }]);
    setChatInput("");
    setChatAttachments([]);

    abortActiveStream();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      let memoryGroupId = "";
      try {
        memoryGroupId = await ensureEverMemConversationGroupId("chat", chatMemoryGroupId);
        if (memoryGroupId && memoryGroupId !== chatMemoryGroupId) {
          const persisted = persistEverMemConversationGroupId("chat", memoryGroupId);
          setChatMemoryGroupId(persisted);
        }
      } catch {
        memoryGroupId = "";
      }

      let streamedReply = "";
      let streamedReasoning = "";
      await streamChatCompletion(
        {
          provider: chatProvider,
          model: chatModel.trim() || undefined,
          messages: apiHistory,
          temperature: 0.7,
          max_tokens: 1024,
          use_memory: useMemory,
          deep_thinking: deepThinking
        },
        {
          onDelta: (chunk) => {
            streamedReply += chunk;
            setChatMessages((prev) => {
              if (!prev.length) {
                return prev;
              }
              const next = [...prev];
              const lastIdx = next.length - 1;
              const last = next[lastIdx];
              if (last.role !== "assistant") {
                return prev;
              }
              next[lastIdx] = { ...last, content: streamedReply };
              return next;
            });
          },
          onReasoning: (chunk) => {
            streamedReasoning += chunk;
            setChatMessages((prev) => {
              if (!prev.length) {
                return prev;
              }
              const next = [...prev];
              const lastIdx = next.length - 1;
              const last = next[lastIdx];
              if (last.role !== "assistant") {
                return prev;
              }
              next[lastIdx] = { ...last, reasoningContent: streamedReasoning };
              return next;
            });
          },
          onDone: (meta) => {
            if (meta?.memoriesRetrieved || meta?.memorySaved) {
              setChatMessages((prev) => {
                const next = [...prev];
                const lastIdx = next.length - 1;
                const prevIdx = lastIdx - 1;

                if (meta.memorySaved && prevIdx >= 0 && next[prevIdx].role === "user") {
                  next[prevIdx] = { ...next[prevIdx], memorySaved: true };
                }
                if (meta.memoriesRetrieved && lastIdx >= 0 && next[lastIdx].role === "assistant") {
                  next[lastIdx] = { ...next[lastIdx], memoriesUsed: meta.memoriesRetrieved };
                }
                return next;
              });
            }
          }
        },
        {
          memoryGroupId: memoryGroupId || undefined,
          signal: controller.signal,
        }
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      setChatMessages((prev) => {
        if (!prev.length) {
          return prev;
        }
        const last = prev[prev.length - 1];
        if (last.role === "assistant" && !last.content.trim()) {
          return prev.slice(0, -1);
        }
        return prev;
      });
      setChatError(formatErrorMessage(err, t("聊天请求失败。", "Chat request failed.")));
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
        setChatBusy(false);
      }
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!chatBusy && chatInput.trim()) {
        event.currentTarget.form?.requestSubmit();
      }
    }
  }

  return {
    chatProvider,
    chatProviderOptions,
    chatModel,
    chatModelOptions,
    chatModelChoices,
    chatModelChoiceValue,
    chatInput,
    chatMessages,
    chatBusy,
    chatError,
    chatMemoryGroupId,
    onSubmit,
    onProviderChange,
    onModelChange: setChatModel,
    onModelChoiceChange,
    onInputChange: setChatInput,
    onQuickAction: setChatInput,
    onComposerKeyDown,
    onNewSession,
    onSelectHistory: setChatInput,
    replaceSession,
    injectMessage,
    onDeleteMessage: deleteMessage,
    onRegenerateMessage: regenerateMessage,
    useMemory,
    setUseMemory,
    deepThinking,
    setDeepThinking,
    chatAttachments,
    addChatAttachment,
    removeChatAttachment,
    clearChatAttachments,
  };
}

export type UseChatResult = ReturnType<typeof useChat>;
