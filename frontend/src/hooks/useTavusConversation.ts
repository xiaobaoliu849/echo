import { useCallback, useEffect, useRef, useState } from "react";
import type { DailyCall, DailyEventObject } from "@daily-co/daily-js";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import { createTavusConversation, endTavusConversation } from "../api";

export type TavusConversationStatus = "idle" | "creating" | "joining" | "connected" | "ended";

export type SubtitleItem = {
  id: string;
  speaker: "user" | "pal";
  speakerName: string;
  text: string;
  isFinal: boolean;
  timestamp: number;
};

type StartParams = {
  palId?: string;
  palName?: string;
  conversationName?: string;
  faceId?: string;
};

type Options = {
  formatErrorMessage: FormatErrorMessage;
  language?: UiLanguage;
};

export type UseTavusConversationResult = {
  status: TavusConversationStatus;
  errorMessage: string;
  localAudioLevel: number;
  isMuted: boolean;
  isVideoOff: boolean;
  isSharingScreen: boolean;
  callDuration: number;
  formattedDuration: string;
  transcripts: SubtitleItem[];
  activeSubtitle: SubtitleItem | null;
  showSubtitles: boolean;
  toggleSubtitles: () => void;
  clearTranscripts: () => void;
  toggleMute: () => void;
  toggleVideo: () => void;
  toggleScreenShare: () => Promise<void>;
  attachVideoContainer: (node: HTMLDivElement | null) => void;
  start: (params?: StartParams) => Promise<void>;
  leave: () => void;
  clearError: () => void;
};

export function parseAppMessageSubtitle(
  rawData: any,
  localSessionId?: string
): {
  speaker: "user" | "pal";
  text: string;
  isFinal: boolean;
  speakerName?: string;
} | null {
  if (!rawData) return null;
  let data = rawData;
  if (typeof rawData === "string") {
    try {
      data = JSON.parse(rawData);
    } catch {
      return { speaker: "pal", text: rawData.trim(), isFinal: true };
    }
  }

  const eventType = String(
    data.event_type ||
    data.eventType ||
    data.type ||
    data.action ||
    data.event ||
    ""
  ).toLowerCase();

  // Skip explicit non-speech control/system events
  if (
    eventType.includes("ping") ||
    eventType.includes("heartbeat") ||
    eventType === "system.pal_joined" ||
    eventType === "system.shutdown" ||
    eventType === "conversation.echo" ||
    eventType.startsWith("room.")
  ) {
    return null;
  }

  // Tavus Interaction Events store speech and role in `properties`.
  // Also check `data.data`, `data.payload`, `data.detail`, or root object.
  const props =
    typeof data.properties === "object" && data.properties !== null
      ? data.properties
      : typeof data.data === "object" && data.data !== null
      ? data.data
      : typeof data.payload === "object" && data.payload !== null
      ? data.payload
      : typeof data.detail === "object" && data.detail !== null
      ? data.detail
      : data;

  const role = String(
    props.role ||
    props.speaker ||
    props.speaker_type ||
    data.role ||
    data.speaker ||
    data.speaker_type ||
    ""
  ).toLowerCase();

  const participantName = String(
    props.participant_name ||
    props.participantName ||
    props.name ||
    data.participant_name ||
    data.participantName ||
    data.name ||
    ""
  ).trim();

  const participantId = String(
    props.participant_id ||
    props.participantId ||
    data.participant_id ||
    data.participantId ||
    data.participantId ||
    ""
  ).toLowerCase();

  const isUser =
    role === "user" ||
    role === "me" ||
    role === "human" ||
    role === "client" ||
    eventType.startsWith("user.") ||
    participantId === "user" ||
    participantId === "local" ||
    (Boolean(localSessionId) && participantId === localSessionId?.toLowerCase()) ||
    participantName.toLowerCase() === "user" ||
    participantName.toLowerCase() === "you" ||
    participantName.toLowerCase() === "echo user";

  const speaker: "user" | "pal" = isUser ? "user" : "pal";

  const text = String(
    props.text ||
    props.speech ||
    props.utterance ||
    props.transcript ||
    props.content ||
    props.message ||
    data.text ||
    data.speech ||
    data.utterance ||
    data.transcript ||
    data.content ||
    data.message ||
    ""
  ).trim();

  if (!text) return null;

  const isStreamingEvent =
    eventType === "conversation.utterance.streaming" ||
    eventType.includes("streaming") ||
    eventType.includes("stream") ||
    Boolean(props.is_streaming || data.is_streaming);

  const isFinal = Boolean(
    !isStreamingEvent ||
    props.is_final ||
    props.isFinal ||
    props.final ||
    props.speech_final ||
    data.is_final ||
    data.isFinal ||
    data.final ||
    eventType === "conversation.utterance" ||
    eventType.includes("completed") ||
    eventType.includes("final")
  );

  return { speaker, text, isFinal, speakerName: participantName || undefined };
}

// Fires after the last remote participant (the PAL) leaves, so a stray
// network blip does not kill a call that is about to resume.
const PAL_LEFT_LEAVE_DELAY_MS = 1500;

export default function useTavusConversation({
  formatErrorMessage,
  language = "zh-CN",
}: Options): UseTavusConversationResult {
  const t = createInlineTranslator(language);
  const callRef = useRef<DailyCall | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const conversationIdRef = useRef<string>("");
  const activePalNameRef = useRef<string>("");
  const startGenerationRef = useRef(0);
  const startingRef = useRef(false);
  const autoLeaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeSubtitleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<TavusConversationStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [localAudioLevel, setLocalAudioLevel] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);
  const [isSharingScreen, setIsSharingScreen] = useState(false);
  const [callDuration, setCallDuration] = useState(0);
  const [transcripts, setTranscripts] = useState<SubtitleItem[]>([]);
  const [activeSubtitle, setActiveSubtitle] = useState<SubtitleItem | null>(null);
  const [showSubtitles, setShowSubtitles] = useState(true);

  const toggleMute = useCallback(() => {
    const call = callRef.current;
    if (!call) return;
    try {
      const nextMuted = !isMuted;
      call.setLocalAudio(!nextMuted);
      setIsMuted(nextMuted);
    } catch {}
  }, [isMuted]);

  const toggleVideo = useCallback(() => {
    const call = callRef.current;
    if (!call) return;
    try {
      const nextOff = !isVideoOff;
      call.setLocalVideo(!nextOff);
      setIsVideoOff(nextOff);
    } catch {}
  }, [isVideoOff]);

  const toggleScreenShare = useCallback(async () => {
    const call = callRef.current;
    if (!call) return;
    try {
      if (isSharingScreen) {
        call.stopScreenShare();
        setIsSharingScreen(false);
      } else {
        await call.startScreenShare();
        setIsSharingScreen(true);
      }
    } catch {
      // User cancelled screen picker or permission denied
    }
  }, [isSharingScreen]);

  const attachVideoContainer = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node;
  }, []);

  const clearAutoLeaveTimer = useCallback(() => {
    if (autoLeaveTimerRef.current) {
      clearTimeout(autoLeaveTimerRef.current);
      autoLeaveTimerRef.current = null;
    }
  }, []);

  const clearDurationTimer = useCallback(() => {
    if (durationTimerRef.current) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }
  }, []);

  const endConversationUpstream = useCallback((conversationId: string) => {
    if (!conversationId) {
      return;
    }
    void endTavusConversation(conversationId).catch(() => {
      // Best effort: an expired conversation 404s on its own.
    });
  }, []);

  const teardownCall = useCallback(() => {
    clearAutoLeaveTimer();
    clearDurationTimer();
    if (activeSubtitleTimerRef.current) {
      clearTimeout(activeSubtitleTimerRef.current);
      activeSubtitleTimerRef.current = null;
    }
    const call = callRef.current;
    callRef.current = null;
    if (!call) {
      return;
    }
    try {
      void Promise.resolve(call.destroy()).catch(() => {});
    } catch {
      // The frame may already be gone with the unmounted container.
    }
    setLocalAudioLevel(0);
    setIsMuted(false);
    setIsVideoOff(false);
    setIsSharingScreen(false);
    setCallDuration(0);
    setActiveSubtitle(null);
  }, [clearAutoLeaveTimer, clearDurationTimer]);

  const leave = useCallback(() => {
    startGenerationRef.current += 1;
    startingRef.current = false;
    const call = callRef.current;
    const conversationId = conversationIdRef.current;
    conversationIdRef.current = "";
    if (call) {
      try {
        void Promise.resolve(call.leave()).catch(() => {});
      } catch {
        // Teardown below also releases already-ended meetings.
      }
    }
    teardownCall();
    endConversationUpstream(conversationId);
    setStatus((prev) => (prev === "idle" ? prev : "ended"));
  }, [endConversationUpstream, teardownCall]);

  const start = useCallback(async (params: StartParams = {}) => {
    if (callRef.current || startingRef.current) {
      return;
    }
    startingRef.current = true;
    activePalNameRef.current = params.palName?.trim() || "";
    const generation = ++startGenerationRef.current;
    setErrorMessage("");
    setStatus("creating");
    try {
      const conversation = await createTavusConversation({
        palId: params.palId,
        conversationName: params.conversationName,
        faceId: params.faceId,
      });
      if (generation !== startGenerationRef.current) {
        endConversationUpstream(conversation.conversation_id);
        return;
      }
      conversationIdRef.current = conversation.conversation_id;
      setStatus("joining");

      // Dynamic import keeps daily-js (and its WebRTC stack) out of the
      // main bundle; the video page is lazy-loaded on its own. The frame
      // is sized by the .vsPalVideoHost iframe CSS rules.
      const Daily = (await import("@daily-co/daily-js")).default;
      if (generation !== startGenerationRef.current) return;
      const parent = containerRef.current ?? undefined;
      const frame = parent
        ? Daily.createFrame(parent, {
            showLeaveButton: false,
            showFullscreenButton: false,
            showUserNameChangeUI: false,
            theme: {
              colors: {
                accent: "#6366f1",
                accentText: "#ffffff",
                background: "#0f172a",
                backgroundAccent: "#1e293b",
                baseText: "#f8fafc",
                border: "#334155",
                mainAreaBg: "#0b0f19",
                mainAreaBgAccent: "#0f172a",
                mainAreaText: "#f8fafc",
                supportiveText: "#94a3b8",
              },
            },
            iframeStyle: {
              width: "100%",
              height: "100%",
              border: "0",
            },
          })
        : Daily.createFrame();
      callRef.current = frame;

      const handleIncomingSubtitle = (rawEventData: any) => {
        const localSessionId = callRef.current?.participants()?.local?.session_id;
        const parsed = parseAppMessageSubtitle(rawEventData, localSessionId);
        if (!parsed) return;

        const timestamp = Date.now();
        const fallbackPalName = activePalNameRef.current || t("AI 分身", "AI PAL");
        const fallbackName = parsed.speaker === "user" ? t("你", "You") : fallbackPalName;
        const speakerName =
          parsed.speakerName &&
          !["user", "you", "me", "pal", "assistant", "replica"].includes(parsed.speakerName.toLowerCase())
            ? parsed.speakerName
            : fallbackName;

        setTranscripts((prev) => {
          const last = prev[prev.length - 1];
          // If previous message was same speaker within 5s and not final, update it in place
          if (last && last.speaker === parsed.speaker && !last.isFinal && timestamp - last.timestamp < 5000) {
            const updatedItem: SubtitleItem = {
              ...last,
              text: parsed.text,
              isFinal: parsed.isFinal,
              timestamp,
            };
            setActiveSubtitle(updatedItem);
            return [...prev.slice(0, -1), updatedItem];
          }

          // If speaker changed while previous turn was in-progress, seal previous turn as final
          const basePrev =
            last && !last.isFinal && last.speaker !== parsed.speaker
              ? [...prev.slice(0, -1), { ...last, isFinal: true }]
              : prev;

          const newItem: SubtitleItem = {
            id: `sub-${timestamp}-${Math.random().toString(36).slice(2, 6)}`,
            speaker: parsed.speaker,
            speakerName,
            text: parsed.text,
            isFinal: parsed.isFinal,
            timestamp,
          };
          setActiveSubtitle(newItem);
          return [...basePrev, newItem];
        });

        if (activeSubtitleTimerRef.current) {
          clearTimeout(activeSubtitleTimerRef.current);
        }
        activeSubtitleTimerRef.current = setTimeout(() => {
          setActiveSubtitle(null);
        }, 4500);
      };

      frame.on("joined-meeting", () => {
        if (generation !== startGenerationRef.current) return;
        setStatus("connected");
        setCallDuration(0);
        clearDurationTimer();
        durationTimerRef.current = setInterval(() => {
          setCallDuration((prev) => prev + 1);
        }, 1000);
      });
      frame.on("left-meeting", () => {
        if (generation === startGenerationRef.current) leave();
      });
      frame.on("error", (event: DailyEventObject) => {
        const message = (event as { errorMsg?: string }).errorMsg || "";
        if (message) {
          setErrorMessage(message);
        }
      });
      frame.on("local-audio-level" as any, (event: any) => {
        if (typeof event?.audioLevel === "number") {
          setLocalAudioLevel(event.audioLevel);
        }
      });
      frame.on("app-message", (event: any) => {
        handleIncomingSubtitle(event?.data ?? event?.message ?? event);
      });
      frame.on("transcription-message" as any, (event: any) => {
        handleIncomingSubtitle(event);
      });
      frame.on("participant-updated", (event: any) => {
        if (event?.participant?.local) {
          if (typeof event.participant.audio === "boolean") {
            setIsMuted(!event.participant.audio);
          }
          if (typeof event.participant.video === "boolean") {
            setIsVideoOff(!event.participant.video);
          }
          if (typeof event.participant.screen === "boolean") {
            setIsSharingScreen(event.participant.screen);
          }
        }
      });
      frame.on("participant-left", () => {
        if (generation !== startGenerationRef.current) return;
        const activeCall = callRef.current;
        if (!activeCall) {
          return;
        }
        const remaining = Object.entries(activeCall.participants() || {})
          .filter(([id, participant]) => id !== "local" && !participant.local).length;
        if (remaining > 0) {
          return;
        }
        clearAutoLeaveTimer();
        autoLeaveTimerRef.current = setTimeout(() => {
          autoLeaveTimerRef.current = null;
          if (Object.entries(callRef.current?.participants() || {})
            .some(([id, participant]) => id !== "local" && !participant.local)) return;
          leave();
        }, PAL_LEFT_LEAVE_DELAY_MS);
      });

      // Private rooms (require_auth) issue a meeting token that must be
      // passed as the join token; public rooms join by URL alone.
      const meetingToken = conversation.meeting_token?.trim();
      const joinParams: Record<string, any> = {
        url: conversation.conversation_url,
        userName: "Echo User",
      };
      if (meetingToken) {
        joinParams.token = meetingToken;
      }
      await frame.join(joinParams);
      if (generation === startGenerationRef.current) setStatus("connected");
    } catch (error) {
      if (generation !== startGenerationRef.current) return;
      // Billing starts when the conversation is created, so a conversation
      // that was created but never joined must be ended upstream as well.
      const orphanedConversationId = conversationIdRef.current;
      conversationIdRef.current = "";
      teardownCall();
      endConversationUpstream(orphanedConversationId);
      setStatus("idle");
      setErrorMessage(
        formatErrorMessage(error, t("无法开始视频通话。", "Could not start the video conversation."))
      );
    } finally {
      if (generation === startGenerationRef.current) startingRef.current = false;
    }
  }, [clearAutoLeaveTimer, clearDurationTimer, endConversationUpstream, formatErrorMessage, leave, t, teardownCall]);

  const clearError = useCallback(() => {
    setErrorMessage("");
  }, []);

  const toggleSubtitles = useCallback(() => {
    setShowSubtitles((prev) => !prev);
  }, []);

  const clearTranscripts = useCallback(() => {
    setTranscripts([]);
    setActiveSubtitle(null);
  }, []);

  useEffect(() => {
    return () => {
      startGenerationRef.current += 1;
      startingRef.current = false;
      const conversationId = conversationIdRef.current;
      conversationIdRef.current = "";
      teardownCall();
      endConversationUpstream(conversationId);
    };
  }, [endConversationUpstream, teardownCall]);

  const formattedDuration = `${Math.floor(callDuration / 60)
    .toString()
    .padStart(2, "0")}:${(callDuration % 60).toString().padStart(2, "0")}`;

  return {
    status,
    errorMessage,
    localAudioLevel,
    isMuted,
    isVideoOff,
    isSharingScreen,
    callDuration,
    formattedDuration,
    transcripts,
    activeSubtitle,
    showSubtitles,
    toggleSubtitles,
    clearTranscripts,
    toggleMute,
    toggleVideo,
    toggleScreenShare,
    attachVideoContainer,
    start,
    leave,
    clearError,
  };
}
