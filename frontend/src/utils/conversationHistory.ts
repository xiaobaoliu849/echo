import type { ChatMessage } from "../api";
import { createInlineTranslator, localizeText, type UiLanguage } from "../i18n";

export type ConversationArchiveEntry = {
  id: string;
  content: string;
  chatMessages: ChatMessage[];
  voiceMessages: ChatMessage[];
  chatGroupId: string;
  voiceGroupId: string;
  kind?: "chat" | "voice" | "video";
  palConversationId?: string;
  titleCustomized?: boolean;
  updatedAt: number;
};

const MAX_CONVERSATION_HISTORY = 30;

function createLocalArchiveId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function getConversationArchiveKind(entry: ConversationArchiveEntry): "chat" | "voice" | "video" {
  if (entry.palConversationId) return "video";
  if (entry.kind) return entry.kind;
  // Older PAL archives stored the source only in their title.
  if (entry.chatMessages.length === 0 && entry.voiceMessages.length > 0) {
    return /^\[(?:视频[^\]]*|Video(?:\s[^\]]*)?)\]/i.test(entry.content) ? "video" : "voice";
  }
  return "chat";
}

function firstMeaningfulMessage(messages: ChatMessage[]): string {
  const preferred = messages.find((item) => item.role === "user" && item.content.trim());
  const fallback = preferred || messages.find((item) => item.content.trim());
  return fallback ? fallback.content.trim() : "";
}

export function buildConversationHistoryEntry(params: {
  chatMessages: ChatMessage[];
  voiceMessages: ChatMessage[];
  chatGroupId: string;
  voiceGroupId: string;
  language: UiLanguage;
}): ConversationArchiveEntry | null {
  const chatMessages = Array.isArray(params.chatMessages) ? params.chatMessages : [];
  const voiceMessages = Array.isArray(params.voiceMessages) ? params.voiceMessages : [];
  if (chatMessages.length === 0 && voiceMessages.length === 0) return null;

  const baseText = firstMeaningfulMessage(chatMessages) || firstMeaningfulMessage(voiceMessages);
  const preview = baseText.length > 30
    ? `${baseText.slice(0, 30)}...`
    : baseText || localizeText(params.language, "未命名会话", "Untitled Conversation");
  const kind = chatMessages.length === 0 && voiceMessages.length > 0 ? "voice" : "chat";
  const label = kind === "voice"
    ? `${createInlineTranslator(params.language)("[语音]", "[Voice]")} ${preview}`
    : preview;

  return {
    id: createLocalArchiveId(),
    content: label,
    chatMessages: chatMessages.map((item) => ({ ...item })),
    voiceMessages: voiceMessages.map((item) => ({ ...item })),
    chatGroupId: params.chatGroupId.trim(),
    voiceGroupId: params.voiceGroupId.trim(),
    kind,
    updatedAt: Date.now(),
  };
}

export function preserveConversationArchive(
  entry: ConversationArchiveEntry,
  baseline: ConversationArchiveEntry | null,
): ConversationArchiveEntry {
  if (!baseline) return entry;
  const kind = getConversationArchiveKind(baseline);
  return {
    ...entry,
    id: baseline.id,
    kind: kind === "video" ? "video" : entry.kind,
    palConversationId: baseline.palConversationId,
    titleCustomized: baseline.titleCustomized,
    content: kind === "video" || baseline.titleCustomized ? baseline.content : entry.content,
  };
}

export function areMessageListsEqual(left: ChatMessage[], right: ChatMessage[]): boolean {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  if (left.length === 0) return true;
  // Compare the messages most likely to change before serializing the list.
  const lastL = left[left.length - 1];
  const lastR = right[right.length - 1];
  if (lastL.content !== lastR.content || lastL.role !== lastR.role) return false;
  if (left.length === 1) return true;
  const firstL = left[0];
  const firstR = right[0];
  if (firstL.content !== firstR.content || firstL.role !== firstR.role) return false;
  return left.every(({ id: _leftId, ...message }, index) => {
    const { id: _rightId, ...other } = right[index];
    return JSON.stringify(message) === JSON.stringify(other);
  });
}

function areArchiveSourcesEqual(left: ConversationArchiveEntry, right: ConversationArchiveEntry): boolean {
  const kind = getConversationArchiveKind(left);
  if (kind !== getConversationArchiveKind(right)) return false;
  // Two video calls can have identical transcripts and titles.
  return kind !== "video" || left.id === right.id;
}

export function areArchiveEntriesEquivalent(
  left: ConversationArchiveEntry | null,
  right: ConversationArchiveEntry | null,
): boolean {
  if (!left || !right || !areArchiveSourcesEqual(left, right)) return false;
  return (
    left.chatGroupId === right.chatGroupId &&
    left.voiceGroupId === right.voiceGroupId &&
    areMessageListsEqual(left.chatMessages, right.chatMessages) &&
    areMessageListsEqual(left.voiceMessages, right.voiceMessages)
  );
}

export function areArchiveEntriesSameConversationContent(
  left: ConversationArchiveEntry,
  right: ConversationArchiveEntry,
): boolean {
  return (
    areArchiveSourcesEqual(left, right) &&
    areMessageListsEqual(left.chatMessages, right.chatMessages) &&
    areMessageListsEqual(left.voiceMessages, right.voiceMessages)
  );
}

export function areArchiveTitlesDuplicate(left: ConversationArchiveEntry, right: ConversationArchiveEntry): boolean {
  return getConversationArchiveKind(left) !== "video" &&
    areArchiveSourcesEqual(left, right) && left.content === right.content;
}

export function normalizeConversationHistory(entries: ConversationArchiveEntry[]): ConversationArchiveEntry[] {
  const normalized: ConversationArchiveEntry[] = [];
  for (const entry of entries) {
    const hasDuplicate = normalized.some((item) => (
      item.id === entry.id ||
      areArchiveTitlesDuplicate(item, entry) ||
      areArchiveEntriesEquivalent(item, entry) ||
      areArchiveEntriesSameConversationContent(item, entry)
    ));
    if (!hasDuplicate) {
      normalized.push({ ...entry, kind: getConversationArchiveKind(entry) });
    }
  }
  return normalized.slice(0, MAX_CONVERSATION_HISTORY);
}
