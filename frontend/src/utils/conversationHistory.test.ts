import { describe, expect, it } from "vitest";
import {
  areMessageListsEqual,
  buildConversationHistoryEntry,
  normalizeConversationHistory,
  preserveConversationArchive,
  type ConversationArchiveEntry,
} from "./conversationHistory";

function videoArchive(overrides: Partial<ConversationArchiveEntry> = {}): ConversationArchiveEntry {
  return {
    id: "video-call",
    content: "[视频 Mia] 你好",
    chatMessages: [],
    voiceMessages: [{ role: "user", content: "你好" }, { role: "assistant", content: "你好！" }],
    chatGroupId: "",
    voiceGroupId: "",
    kind: "video",
    palConversationId: "call-1",
    updatedAt: 1,
    ...overrides,
  };
}

function restoredEntry(baseline: ConversationArchiveEntry, language: "zh-CN" | "en-US" = "zh-CN") {
  return buildConversationHistoryEntry({
    chatMessages: baseline.chatMessages,
    voiceMessages: baseline.voiceMessages.map((message, index) => ({ ...message, id: `restored-${index}` })),
    chatGroupId: baseline.chatGroupId,
    voiceGroupId: baseline.voiceGroupId,
    language,
  })!;
}

describe("conversation archives", () => {
  it.each(["zh-CN", "en-US"] as const)("retains video source and title on %s autosave", (language) => {
    const baseline = videoArchive();
    const entry = preserveConversationArchive(restoredEntry(baseline, language), baseline);
    expect(entry).toMatchObject({ id: baseline.id, content: baseline.content, kind: "video", palConversationId: "call-1" });
  });

  it.each(["[视频 Mia] 你好", "[视频PAL] 你好", "[Video Mia] Hello", "[Video PAL] Hello"])(
    "recognizes and preserves legacy title %s", (content) => {
      const legacy = videoArchive({ kind: undefined, palConversationId: undefined, content });
      const [migrated] = normalizeConversationHistory([legacy]);
      expect(migrated.kind).toBe("video");
      const entry = preserveConversationArchive(restoredEntry(migrated, "en-US"), migrated);
      expect(entry).toMatchObject({ id: legacy.id, content, kind: "video" });
    },
  );

  it("retains video title when a restored conversation gains text messages", () => {
    const baseline = videoArchive();
    const entry = preserveConversationArchive({
      ...restoredEntry(baseline), chatMessages: [{ role: "user", content: "继续讨论" }],
    }, baseline);
    expect(entry.content).toBe(baseline.content);
    expect(entry.kind).toBe("video");
    expect(entry.chatMessages[0].content).toBe("继续讨论");
  });

  it("preserves customized titles for video and ordinary chats", () => {
    for (const baseline of [videoArchive(), videoArchive({ kind: "chat", palConversationId: undefined })]) {
      const renamed = { ...baseline, content: "我的会议笔记", titleCustomized: true };
      const entry = preserveConversationArchive(restoredEntry(renamed, "en-US"), renamed);
      expect(entry.content).toBe("我的会议笔记");
      expect(entry.titleCustomized).toBe(true);
    }
  });

  it("keeps distinct identical video calls separate after migration and reload", () => {
    const legacy = videoArchive({ kind: undefined, palConversationId: undefined });
    const modern = videoArchive({ id: "another-call", palConversationId: "call-2" });
    const normalized = normalizeConversationHistory([modern, legacy, { ...modern }]);
    expect(normalized).toHaveLength(2);
    expect(normalizeConversationHistory(JSON.parse(JSON.stringify(normalized)))).toHaveLength(2);
  });

  it("does not merge an audio archive with an identical video transcript", () => {
    const video = videoArchive();
    const audio = { ...video, id: "audio-call", content: "[语音] 你好", kind: "voice" as const, palConversationId: undefined };
    expect(normalizeConversationHistory([video, audio])).toHaveLength(2);
  });

  it("ignores restored message IDs while comparing saved content", () => {
    const baseline = videoArchive();
    expect(areMessageListsEqual(baseline.voiceMessages, restoredEntry(baseline).voiceMessages)).toBe(true);
    const updated = restoredEntry(baseline).voiceMessages;
    updated[1] = { ...updated[1], content: "Different answer" };
    expect(areMessageListsEqual(baseline.voiceMessages, updated)).toBe(false);
  });
});
