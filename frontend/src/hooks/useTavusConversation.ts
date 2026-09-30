import { useCallback, useEffect, useRef, useState } from "react";
import type { DailyCall, DailyEventObject } from "@daily-co/daily-js";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import { createTavusConversation, endTavusConversation } from "../api";

export type TavusConversationStatus =
  | "idle"
  | "creating"
  | "prejoin"
  | "joining"
  | "connected"
  | "ended";

export type SubtitleItem = {
  id: string;
  speaker: "user" | "pal";
  speakerName: string;
  text: string;
  isFinal: boolean;
  timestamp: number;
  // Receipt time on the local clock. The fallback merge window uses this —
  // never `timestamp`, which comes from Tavus's clock and can be skewed.
  receivedAt: number;
  // Tavus turn_idx groups every event of one conversation turn; used to
  // merge streaming utterances exactly instead of guessing by time window.
  turnIdx?: number;
};

type StartParams = {
  palId?: string;
  palName?: string;
  conversationName?: string;
  faceId?: string;
  // Per-conversation Tavus overrides, e.g. { language: "multilingual" }.
  properties?: Record<string, unknown>;
  // Free conversation where the PAL never joins (setup validation).
  testMode?: boolean;
};

type Options = {
  formatErrorMessage: FormatErrorMessage;
  language?: UiLanguage;
  onConversationEnded?: (transcripts: SubtitleItem[], palName: string, conversationId: string) => void;
};

// Selected device preferences survive restarts so a working setup does not
// need to be picked again before every call.
const DEVICE_PREFS_STORAGE_KEY = "vs_pal_device_prefs";

type DevicePrefs = {
  camera?: string;
  microphone?: string;
  speaker?: string;
};

function loadDevicePrefs(): DevicePrefs {
  try {
    const raw = localStorage.getItem(DEVICE_PREFS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveDevicePrefs(patch: Partial<DevicePrefs>): void {
  try {
    const next = { ...loadDevicePrefs(), ...patch };
    localStorage.setItem(DEVICE_PREFS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

export type UseTavusConversationResult = {
  status: TavusConversationStatus;
  errorMessage: string;
  localAudioLevel: number;
  isMuted: boolean;
  isVideoOff: boolean;
  isSharingScreen: boolean;
  isPalSpeaking: boolean;
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
  // Media tracks for self-rendered <video> elements (headless callObject mode).
  localVideoTrack: MediaStreamTrack | null;
  localScreenTrack: MediaStreamTrack | null;
  remoteVideoTrack: MediaStreamTrack | null;
  remoteAudioTrack: MediaStreamTrack | null;
  remoteScreenAudioTrack: MediaStreamTrack | null;
  // Device selection for the Chinese prejoin screen.
  cameras: MediaDeviceInfo[];
  microphones: MediaDeviceInfo[];
  speakers: MediaDeviceInfo[];
  selectedCameraId: string;
  selectedMicrophoneId: string;
  selectedSpeakerId: string;
  cameraError: string;
  isCheckingDevices: boolean;
  retryCamera: () => Promise<void>;
  selectCamera: (deviceId: string) => Promise<void>;
  selectMicrophone: (deviceId: string) => Promise<void>;
  selectSpeaker: (deviceId: string) => Promise<void>;
  start: (params?: StartParams) => Promise<void>;
  join: (options?: { videoOff?: boolean }) => Promise<void>;
  cancelPrejoin: () => void;
  leave: () => void;
  clearError: () => void;
};

function toFiniteNumber(value: any): number | undefined {
  const num = typeof value === "string" ? Number(value) : value;
  return typeof num === "number" && Number.isFinite(num) ? num : undefined;
}

// Interaction events carry `timestamp` as a Unix epoch float in seconds
// (same unit as the transcript webhook); normalize to epoch milliseconds.
function toEpochMs(value: number | undefined): number | undefined {
  if (value === undefined) return undefined;
  return value < 1e12 ? Math.round(value * 1000) : Math.round(value);
}

export type ParsedTavusSpeech = {
  speaker: "user" | "pal";
  text: string;
  isFinal: boolean;
  speakerName?: string;
  // Globally monotonic event sequence number (drop stale arrivals).
  seq?: number;
  // Groups all events belonging to one conversation turn.
  turnIdx?: number;
  // Event time in epoch milliseconds, normalized from Tavus seconds.
  timestamp?: number;
};

export function parseAppMessageSubtitle(
  rawData: any,
  localSessionId?: string
): ParsedTavusSpeech | null {
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

  const seq = toFiniteNumber(data.seq ?? props.seq);
  const turnIdx = toFiniteNumber(data.turn_idx ?? data.turnIdx ?? props.turn_idx ?? props.turnIdx);
  const timestamp = toEpochMs(toFiniteNumber(data.timestamp ?? props.timestamp));

  return {
    speaker,
    text,
    isFinal,
    speakerName: participantName || undefined,
    ...(seq !== undefined ? { seq } : {}),
    ...(turnIdx !== undefined ? { turnIdx } : {}),
    ...(timestamp !== undefined ? { timestamp } : {}),
  };
}

export type TavusControlEvent =
  // conversation.started_speaking / conversation.stopped_speaking fire for
  // both sides; `interrupted` marks a PAL turn cut short by the user.
  | { type: "speaking"; speaker: "user" | "pal"; speaking: boolean; interrupted: boolean; seq?: number }
  // conversation.joined / conversation.left fire when either side enters or
  // leaves the room; more reliable than participant-left for PAL presence.
  | { type: "presence"; speaker: "user" | "pal"; present: boolean; seq?: number };

function normalizeTavusRole(role: string): "user" | "pal" | null {
  // Tavus also broadcasts legacy duplicates that say "replica" for "pal".
  if (["user", "me", "human", "client"].includes(role)) return "user";
  if (["pal", "replica", "assistant"].includes(role)) return "pal";
  return null;
}

export function parseAppMessageControlEvent(rawData: any): TavusControlEvent | null {
  if (!rawData) return null;
  let data = rawData;
  if (typeof rawData === "string") {
    try {
      data = JSON.parse(rawData);
    } catch {
      return null;
    }
  }
  if (typeof data !== "object" || data === null) return null;

  const eventType = String(
    data.event_type || data.eventType || data.type || ""
  ).toLowerCase();
  const props =
    typeof data.properties === "object" && data.properties !== null ? data.properties : data;
  const seq = toFiniteNumber(data.seq ?? props.seq);
  // Presence/speaking events identify the side explicitly; if the role is
  // missing we return null rather than guess (a wrong guess could end a call).
  const speaker = normalizeTavusRole(String(props.role ?? data.role ?? "").toLowerCase());
  if (!speaker) return null;

  if (eventType === "conversation.started_speaking" || eventType === "conversation.stopped_speaking") {
    return {
      type: "speaking",
      speaker,
      speaking: eventType === "conversation.started_speaking",
      interrupted: Boolean(props.interrupted ?? data.interrupted),
      ...(seq !== undefined ? { seq } : {}),
    };
  }
  if (eventType === "conversation.joined" || eventType === "conversation.left") {
    return {
      type: "presence",
      speaker,
      present: eventType === "conversation.joined",
      ...(seq !== undefined ? { seq } : {}),
    };
  }
  return null;
}

// Grace period before ending a call the PAL has left, so a stray network
// blip does not kill a call that is about to resume.
const PAL_LEFT_LEAVE_DELAY_MS = 1500;

export default function useTavusConversation({
  formatErrorMessage,
  language = "zh-CN",
  onConversationEnded,
}: Options): UseTavusConversationResult {
  const t = createInlineTranslator(language);
  const onConversationEndedRef = useRef(onConversationEnded);
  onConversationEndedRef.current = onConversationEnded;
  const transcriptsRef = useRef<SubtitleItem[]>([]);
  const endedConversationRef = useRef("");
  const callRef = useRef<DailyCall | null>(null);
  const joinedRef = useRef(false);
  const conversationIdRef = useRef<string>("");
  const roomUrlRef = useRef<string>("");
  const meetingTokenRef = useRef<string>("");
  const activePalNameRef = useRef<string>("");
  const startGenerationRef = useRef(0);
  const startingRef = useRef(false);
  const joiningRef = useRef(false);
  // False once camera acquisition failed; join() then passes startVideoOff so
  // a busy camera (Zoom, NVIDIA Broadcast…) cannot block the call.
  const cameraAvailableRef = useRef(true);
  const deviceOperationRef = useRef(false);
  const [isCheckingDevices, setIsCheckingDevices] = useState(false);
  const autoLeaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeSubtitleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Highest interaction-event seq processed; older arrivals are stale.
  const lastSeqRef = useRef<number>(-Infinity);
  const statusRef = useRef<TavusConversationStatus>("idle");
  const [status, setStatus] = useState<TavusConversationStatus>("idle");
  const updateStatus = useCallback((next: TavusConversationStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);
  const [errorMessage, setErrorMessage] = useState("");
  const [cameraError, setCameraError] = useState("");
  const [localAudioLevel, setLocalAudioLevel] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);
  const [isSharingScreen, setIsSharingScreen] = useState(false);
  const [isPalSpeaking, setIsPalSpeaking] = useState(false);
  const [callDuration, setCallDuration] = useState(0);
  const [transcripts, setTranscripts] = useState<SubtitleItem[]>([]);
  const updateTranscripts = useCallback((update: (prev: SubtitleItem[]) => SubtitleItem[]) => {
    const next = update(transcriptsRef.current);
    transcriptsRef.current = next;
    setTranscripts(next);
  }, []);
  const notifyConversationEnded = useCallback((conversationId: string) => {
    if (!conversationId || endedConversationRef.current === conversationId) return;
    endedConversationRef.current = conversationId;
    onConversationEndedRef.current?.(transcriptsRef.current, activePalNameRef.current, conversationId);
  }, []);
  const [activeSubtitle, setActiveSubtitle] = useState<SubtitleItem | null>(null);
  const [showSubtitles, setShowSubtitles] = useState(true);
  const [localVideoTrack, setLocalVideoTrack] = useState<MediaStreamTrack | null>(null);
  const [localScreenTrack, setLocalScreenTrack] = useState<MediaStreamTrack | null>(null);
  const [remoteVideoTrack, setRemoteVideoTrack] = useState<MediaStreamTrack | null>(null);
  const [remoteAudioTrack, setRemoteAudioTrack] = useState<MediaStreamTrack | null>(null);
  const [remoteScreenAudioTrack, setRemoteScreenAudioTrack] = useState<MediaStreamTrack | null>(null);
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([]);
  const [microphones, setMicrophones] = useState<MediaDeviceInfo[]>([]);
  const [speakers, setSpeakers] = useState<MediaDeviceInfo[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [selectedMicrophoneId, setSelectedMicrophoneId] = useState("");
  const [selectedSpeakerId, setSelectedSpeakerId] = useState("");

  // Re-read participants() and mirror the track states we render ourselves.
  // Runs on every track/participant lifecycle event.
  const syncTracks = useCallback(() => {
    const call = callRef.current;
    if (!call || typeof call.participants !== "function") return;
    let participants: Record<string, any> = {};
    try {
      participants = (call.participants() as Record<string, any>) || {};
    } catch {
      return;
    }
    const values = Object.values(participants);
    const local = participants.local ?? values.find((participant) => participant?.local);
    const remote = values.find((participant) => participant && !participant.local);
    const visibleTrack = (state: { state?: string; track?: MediaStreamTrack; persistentTrack?: MediaStreamTrack } | undefined, localTrack = false) =>
      state && (!state.state || state.state === "playable" || (localTrack && state.state === "sendable"))
        ? state.track ?? state.persistentTrack ?? null
        : null;
    setLocalVideoTrack(visibleTrack(local?.tracks?.video, true));
    setLocalScreenTrack(visibleTrack(local?.tracks?.screenVideo, true));
    setRemoteVideoTrack(visibleTrack(remote?.tracks?.video));
    setRemoteAudioTrack(visibleTrack(remote?.tracks?.audio));
    setRemoteScreenAudioTrack(visibleTrack(remote?.tracks?.screenAudio));
  }, []);

  // Returns the enumerated lists so callers can act on them immediately —
  // the state updates above are not committed synchronously.
  const refreshDevices = useCallback(async (): Promise<{
    cameras: MediaDeviceInfo[];
    microphones: MediaDeviceInfo[];
    speakers: MediaDeviceInfo[];
  } | null> => {
    const call = callRef.current;
    if (!call || typeof call.enumerateDevices !== "function") return null;
    try {
      const result = await call.enumerateDevices();
      if (callRef.current !== call) return null;
      const list: MediaDeviceInfo[] = Array.isArray(result?.devices) ? result.devices : [];
      const nextCameras = list.filter((device) => device.kind === "videoinput");
      const nextMicrophones = list.filter((device) => device.kind === "audioinput");
      const nextSpeakers = list.filter((device) => device.kind === "audiooutput");
      setCameras(nextCameras);
      setMicrophones(nextMicrophones);
      setSpeakers(nextSpeakers);
      // Drop selections whose device disappeared (unplugged camera etc.).
      setSelectedCameraId((prev) => (prev && nextCameras.some((d) => d.deviceId === prev) ? prev : ""));
      setSelectedMicrophoneId((prev) => (prev && nextMicrophones.some((d) => d.deviceId === prev) ? prev : ""));
      setSelectedSpeakerId((prev) => (prev && nextSpeakers.some((d) => d.deviceId === prev) ? prev : ""));
      return { cameras: nextCameras, microphones: nextMicrophones, speakers: nextSpeakers };
    } catch {
      // Device enumeration is best-effort; the selects stay empty.
      return null;
    }
  }, []);

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
        // Daily reports success or picker cancellation through events.
      }
    } catch {
      // User cancelled screen picker or permission denied
    }
  }, [isSharingScreen]);

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
    if (call) {
      try {
        call.stopLocalAudioLevelObserver();
      } catch {}
      try {
        void Promise.resolve(call.destroy()).catch(() => {});
      } catch {
        // The call may already be gone during page teardown.
      }
    }
    cameraAvailableRef.current = true;
    deviceOperationRef.current = false;
    setIsCheckingDevices(false);
    joinedRef.current = false;
    setLocalAudioLevel(0);
    setIsMuted(false);
    setIsVideoOff(false);
    setIsSharingScreen(false);
    setIsPalSpeaking(false);
    setCallDuration(0);
    setActiveSubtitle(null);
    setLocalVideoTrack(null);
    setLocalScreenTrack(null);
    setRemoteVideoTrack(null);
    setRemoteAudioTrack(null);
    setRemoteScreenAudioTrack(null);
    setCameraError("");
  }, [clearAutoLeaveTimer, clearDurationTimer]);

  const leave = useCallback(() => {
    startGenerationRef.current += 1;
    startingRef.current = false;
    joiningRef.current = false;
    const call = callRef.current;
    const conversationId = conversationIdRef.current;
    conversationIdRef.current = "";
    roomUrlRef.current = "";
    meetingTokenRef.current = "";
    if (call && joinedRef.current) {
      try {
        void Promise.resolve(call.leave()).catch(() => {});
      } catch {
        // Teardown below also releases already-ended meetings.
      }
    }
    teardownCall();
    endConversationUpstream(conversationId);
    notifyConversationEnded(conversationId);
    const wasActive = statusRef.current !== "idle";
    updateStatus(wasActive ? "ended" : "idle");
  }, [endConversationUpstream, notifyConversationEnded, teardownCall, updateStatus]);

  // Back out of the prejoin screen without starting a call.
  const cancelPrejoin = useCallback(() => {
    startGenerationRef.current += 1;
    startingRef.current = false;
    joiningRef.current = false;
    const conversationId = conversationIdRef.current;
    conversationIdRef.current = "";
    roomUrlRef.current = "";
    meetingTokenRef.current = "";
    teardownCall();
    endConversationUpstream(conversationId);
    updateStatus("idle");
  }, [endConversationUpstream, teardownCall, updateStatus]);

  // Fires after the last remote participant (the PAL) leaves, so a stray
  // network blip does not kill a call that is about to resume. Shared by the
  // Daily participant-left event and the Tavus conversation.left app-message.
  const scheduleAutoLeaveWhenAlone = useCallback(() => {
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
  }, [clearAutoLeaveTimer, leave]);

  const start = useCallback(async (params: StartParams = {}) => {
    if (callRef.current || startingRef.current) {
      return;
    }
    startingRef.current = true;
    activePalNameRef.current = params.palName?.trim() || "";
    endedConversationRef.current = "";
    updateTranscripts(() => []);
    const generation = ++startGenerationRef.current;
    lastSeqRef.current = -Infinity;
    joinedRef.current = false;
    setCallDuration(0);
    setIsPalSpeaking(false);
    setActiveSubtitle(null);
    setErrorMessage("");
    setCameraError("");
    updateStatus("creating");
    try {
      const conversation = await createTavusConversation({
        palId: params.palId,
        conversationName: params.conversationName,
        faceId: params.faceId,
        properties: params.properties,
        testMode: params.testMode,
      });
      if (generation !== startGenerationRef.current) {
        endConversationUpstream(conversation.conversation_id);
        return;
      }
      conversationIdRef.current = conversation.conversation_id;
      roomUrlRef.current = conversation.conversation_url;
      meetingTokenRef.current = conversation.meeting_token?.trim() || "";

      // Headless mode: no Daily iframe, so no English prebuilt UI. We render
      // the video ourselves and show our own Chinese device-check screen.
      // Dynamic import keeps daily-js (and its WebRTC stack) out of the main
      // bundle; the video page is lazy-loaded on its own.
      const Daily = (await import("@daily-co/daily-js")).default;
      if (generation !== startGenerationRef.current) return;
      const call = Daily.createCallObject();
      callRef.current = call;

      const handleIncomingSubtitle = (rawEventData: any) => {
        const localSessionId = callRef.current?.participants()?.local?.session_id;
        const parsed = parseAppMessageSubtitle(rawEventData, localSessionId);
        if (!parsed) return;
        // seq is globally monotonic; a lower-seq event arrived out of order.
        if (parsed.seq !== undefined) {
          if (parsed.seq < lastSeqRef.current) return;
          lastSeqRef.current = parsed.seq;
        }

        const timestamp = parsed.timestamp ?? Date.now();
        const fallbackPalName = activePalNameRef.current || t("AI 分身", "AI PAL");
        const fallbackName = parsed.speaker === "user" ? t("你", "You") : fallbackPalName;
        const speakerName =
          parsed.speakerName &&
          !["user", "you", "me", "pal", "assistant", "replica"].includes(parsed.speakerName.toLowerCase())
            ? parsed.speakerName
            : fallbackName;

        updateTranscripts((prev) => {
          const last = prev[prev.length - 1];
          // Exact turn grouping when both sides carry turn_idx; otherwise
          // fall back to the legacy same-speaker-within-5s heuristic.
          const sameTurn =
            parsed.turnIdx !== undefined && last?.turnIdx !== undefined
              ? last.turnIdx === parsed.turnIdx
              : undefined;

          const now = Date.now();
          if (
            last &&
            last.speaker === parsed.speaker &&
            !last.isFinal &&
            (sameTurn === true || (sameTurn === undefined && now - last.receivedAt < 5000))
          ) {
            const updatedItem: SubtitleItem = {
              ...last,
              text: parsed.text,
              isFinal: parsed.isFinal,
              timestamp,
              receivedAt: now,
              turnIdx: last.turnIdx ?? parsed.turnIdx,
            };
            setActiveSubtitle(updatedItem);
            return [...prev.slice(0, -1), updatedItem];
          }

          // Seal a dangling non-final turn: the speaker changed, or Tavus
          // moved on to a new turn_idx (e.g. after an interruption).
          const basePrev =
            last && !last.isFinal && (last.speaker !== parsed.speaker || sameTurn === false)
              ? [...prev.slice(0, -1), { ...last, isFinal: true }]
              : prev;

          const newItem: SubtitleItem = {
            id: `sub-${timestamp}-${Math.random().toString(36).slice(2, 6)}`,
            speaker: parsed.speaker,
            speakerName,
            text: parsed.text,
            isFinal: parsed.isFinal,
            timestamp,
            receivedAt: now,
            ...(parsed.turnIdx !== undefined ? { turnIdx: parsed.turnIdx } : {}),
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

      const handleIncomingAppMessage = (rawEventData: any) => {
        const control = parseAppMessageControlEvent(rawEventData);
        if (!control) {
          handleIncomingSubtitle(rawEventData);
          return;
        }
        if (control.seq !== undefined) {
          if (control.seq < lastSeqRef.current) return;
          lastSeqRef.current = control.seq;
        }
        if (control.type === "speaking") {
          if (control.speaker !== "pal") return;
          setIsPalSpeaking(control.speaking);
          // An interrupted PAL turn is over: seal its in-progress subtitle so
          // the user's reply starts a fresh entry instead of merging into it.
          if (!control.speaking && control.interrupted) {
            updateTranscripts((prev) => {
              const last = prev[prev.length - 1];
              if (!last || last.speaker !== "pal" || last.isFinal) return prev;
              return [...prev.slice(0, -1), { ...last, isFinal: true }];
            });
          }
          return;
        }
        if (control.speaker !== "pal") return;
        if (control.present) {
          // PAL (re)joined: cancel any pending auto-leave.
          clearAutoLeaveTimer();
        } else {
          scheduleAutoLeaveWhenAlone();
        }
      };

      call.on("joined-meeting", () => {
        if (generation !== startGenerationRef.current) return;
        joinedRef.current = true;
        updateStatus("connected");
        clearDurationTimer();
        durationTimerRef.current = setInterval(() => {
          setCallDuration((prev) => prev + 1);
        }, 1000);
      });
      call.on("left-meeting", () => {
        if (generation === startGenerationRef.current) leave();
      });
      call.on("error", (event: DailyEventObject) => {
        if (generation !== startGenerationRef.current) return;
        const message = (event as { error?: { msg?: string }; errorMsg?: string }).error?.msg ||
          (event as { errorMsg?: string }).errorMsg || "";
        if (message) setErrorMessage(message);
      });
      call.on("camera-error", (event: any) => {
        if (generation !== startGenerationRef.current) return;
        const info = event?.errorMsg || {};
        const blockedMedia: string[] = event?.error?.blockedMedia || [];
        const missingMedia: string[] = event?.error?.missingMedia || [];
        const failureType = String(event?.error?.type || "");
        const videoFailed = info.videoOk === false ||
          blockedMedia.includes("video") || missingMedia.includes("video") ||
          /cam|video/i.test(failureType) ||
          /camera|video/i.test(String(info.errorMsg || ""));
        if (info.audioOk === false || blockedMedia.includes("audio") || missingMedia.includes("audio") || /mic/i.test(failureType)) {
          setErrorMessage(t("无法访问麦克风，请检查系统权限或关闭占用麦克风的应用。", "Could not access the microphone. Check permissions or close other apps using it."));
        }
        if (!videoFailed) return;
        cameraAvailableRef.current = false;
        setCameraError(
          t(
            "无法访问摄像头。它可能正被其他应用（如 Zoom、Teams 或 NVIDIA Broadcast）占用。你可以关闭那些应用后重试，或不使用摄像头加入。",
            "Could not access the camera. It may be in use by another app (e.g. Zoom, Teams, or NVIDIA Broadcast). Close those apps and retry, or join without the camera."
          )
        );
      });
      call.on("started-camera", () => {
        if (generation !== startGenerationRef.current) return;
        const video = call.participants()?.local?.tracks?.video;
        if (video?.state === "blocked" || (!video?.track && !video?.persistentTrack)) return;
        cameraAvailableRef.current = true;
        setCameraError("");
        syncTracks();
        void refreshDevices();
      });
      call.on("available-devices-updated", () => {
        if (generation === startGenerationRef.current) void refreshDevices();
      });
      call.on("local-audio-level" as any, (event: any) => {
        if (generation === startGenerationRef.current && typeof event?.audioLevel === "number") {
          setLocalAudioLevel(event.audioLevel);
        }
      });
      call.on("app-message", (event: any) => {
        if (generation === startGenerationRef.current) {
          handleIncomingAppMessage(event?.data ?? event?.message ?? event);
        }
      });
      call.on("transcription-message" as any, (event: any) => {
        if (generation === startGenerationRef.current) handleIncomingSubtitle(event);
      });
      call.on("local-screen-share-started", () => {
        if (generation !== startGenerationRef.current) return;
        setIsSharingScreen(true);
        syncTracks();
      });
      const handleScreenShareStopped = () => {
        if (generation !== startGenerationRef.current) return;
        setIsSharingScreen(false);
        syncTracks();
      };
      call.on("local-screen-share-stopped", handleScreenShareStopped);
      call.on("local-screen-share-canceled", handleScreenShareStopped);
      call.on("participant-joined", () => {
        if (generation === startGenerationRef.current) syncTracks();
      });
      call.on("participant-updated", (event: any) => {
        if (generation !== startGenerationRef.current) return;
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
        syncTracks();
      });
      call.on("track-started", () => {
        if (generation === startGenerationRef.current) syncTracks();
      });
      call.on("track-stopped", () => {
        if (generation === startGenerationRef.current) syncTracks();
      });
      call.on("participant-left", () => {
        if (generation !== startGenerationRef.current) return;
        syncTracks();
        scheduleAutoLeaveWhenAlone();
      });

      // Check camera and microphone before showing the join button, so the
      // user cannot join while permission or a device switch is pending.
      try {
        await call.startCamera();
      } catch {
        // The camera-error event carries specifics; if it never fired, fall
        // back to a generic message so the user can still join audio-only.
        if (generation === startGenerationRef.current && cameraAvailableRef.current) {
          cameraAvailableRef.current = false;
          setCameraError(
            t(
              "无法打开摄像头或麦克风，请检查系统权限设置。你也可以不使用摄像头加入。",
              "Could not open the camera or microphone. Check system permissions, or join without the camera."
            )
          );
        }
      }
      if (generation !== startGenerationRef.current) return;
      const deviceLists = await refreshDevices();
      if (generation !== startGenerationRef.current) return;
      // Some browser/device failures do not reject startCamera. Read the
      // participant's track status as a fallback for camera-error events.
      const localCamera = call.participants()?.local?.tracks?.video;
      if (localCamera?.state === "blocked" && !localCamera.track && !localCamera.persistentTrack && cameraAvailableRef.current) {
        cameraAvailableRef.current = false;
        setCameraError(t("摄像头不可用。请检查权限、关闭占用摄像头的应用，或不使用摄像头加入。", "Camera unavailable. Check permissions, close other apps using it, or join without camera."));
      }
      syncTracks();
      const prefs = loadDevicePrefs();
      if (deviceLists) {
        const inputSelection: { videoDeviceId?: string; audioDeviceId?: string } = {};
        if (prefs.camera && deviceLists.cameras.some((d) => d.deviceId === prefs.camera)) {
          inputSelection.videoDeviceId = prefs.camera;
          setSelectedCameraId(prefs.camera);
        }
        if (prefs.microphone && deviceLists.microphones.some((d) => d.deviceId === prefs.microphone)) {
          inputSelection.audioDeviceId = prefs.microphone;
          setSelectedMicrophoneId(prefs.microphone);
        }
        if (Object.keys(inputSelection).length > 0) {
          try {
            await call.setInputDevicesAsync(inputSelection);
          } catch {
            // The device may have become unavailable between enumeration and selection.
          }
        }
        if (prefs.speaker && deviceLists.speakers.some((d) => d.deviceId === prefs.speaker)) {
          try {
            await call.setOutputDeviceAsync({ outputDeviceId: prefs.speaker });
            setSelectedSpeakerId(prefs.speaker);
          } catch {
            // Keep the system default output when a saved speaker disappeared.
          }
        }
      }
      if (generation !== startGenerationRef.current) return;
      syncTracks();
      updateStatus("prejoin");
    } catch (error) {
      if (generation !== startGenerationRef.current) return;
      // Billing starts when the conversation is created, so a conversation
      // that was created but never joined must be ended upstream as well.
      const orphanedConversationId = conversationIdRef.current;
      conversationIdRef.current = "";
      roomUrlRef.current = "";
      meetingTokenRef.current = "";
      teardownCall();
      endConversationUpstream(orphanedConversationId);
      updateStatus("idle");
      setErrorMessage(
        formatErrorMessage(error, t("无法开始视频通话。", "Could not start the video conversation."))
      );
    } finally {
      if (generation === startGenerationRef.current) startingRef.current = false;
    }
  }, [clearAutoLeaveTimer, clearDurationTimer, endConversationUpstream, formatErrorMessage, leave, scheduleAutoLeaveWhenAlone, t, teardownCall, updateStatus, updateTranscripts]);

  const join = useCallback(async (options: { videoOff?: boolean } = {}) => {
    const call = callRef.current;
    if (!call || statusRef.current !== "prejoin" || joiningRef.current || joinedRef.current || deviceOperationRef.current) {
      return;
    }
    const url = roomUrlRef.current;
    if (!url) {
      return;
    }
    joiningRef.current = true;
    const generation = startGenerationRef.current;
    setErrorMessage("");
    updateStatus("joining");
    try {
      const joinParams: Record<string, any> = {
        url,
        userName: "Echo User",
      };
      if (meetingTokenRef.current) {
        joinParams.token = meetingTokenRef.current;
      }
      if (options.videoOff || !cameraAvailableRef.current) {
        joinParams.startVideoOff = true;
      }
      try {
        await call.startLocalAudioLevelObserver(100);
      } catch {
        // The level meter is optional, including on browsers without AudioWorklet.
      }
      if (generation !== startGenerationRef.current) return;
      await call.join(joinParams);
      if (generation === startGenerationRef.current) {
        joinedRef.current = true;
        updateStatus("connected");
      }
    } catch (error) {
      if (generation !== startGenerationRef.current) return;
      const orphanedConversationId = conversationIdRef.current;
      conversationIdRef.current = "";
      roomUrlRef.current = "";
      meetingTokenRef.current = "";
      teardownCall();
      endConversationUpstream(orphanedConversationId);
      updateStatus("idle");
      setErrorMessage(
        formatErrorMessage(error, t("无法接入视频通话。", "Could not join the video conversation."))
      );
    } finally {
      joiningRef.current = false;
    }
  }, [endConversationUpstream, formatErrorMessage, t, teardownCall, updateStatus]);

  const retryCamera = useCallback(async () => {
    const call = callRef.current;
    if (!call || statusRef.current !== "prejoin" || deviceOperationRef.current) return;
    const generation = startGenerationRef.current;
    deviceOperationRef.current = true;
    setIsCheckingDevices(true);
    cameraAvailableRef.current = true;
    try {
      await call.startCamera();
      if (generation !== startGenerationRef.current) return;
      const video = call.participants()?.local?.tracks?.video;
      if (video?.state === "blocked" || !cameraAvailableRef.current) {
        cameraAvailableRef.current = false;
        setCameraError(t("摄像头仍不可用，请检查权限或关闭占用它的应用。", "Camera is still unavailable. Check permissions or close the app using it."));
      } else if (video && !video.track && !video.persistentTrack) {
        cameraAvailableRef.current = false;
        setCameraError(t("摄像头画面未就绪。请重试，或不使用摄像头加入。", "Camera preview is not ready. Retry or join without camera."));
      } else {
        cameraAvailableRef.current = true;
        setCameraError("");
      }
      syncTracks();
      await refreshDevices();
    } catch {
      if (generation === startGenerationRef.current) {
        cameraAvailableRef.current = false;
        setCameraError(t("摄像头仍不可用，请检查权限或关闭占用它的应用。", "Camera is still unavailable. Check permissions or close the app using it."));
      }
    } finally {
      if (generation === startGenerationRef.current) {
        deviceOperationRef.current = false;
        setIsCheckingDevices(false);
      }
    }
  }, [refreshDevices, syncTracks, t]);

  const selectCamera = useCallback(async (deviceId: string) => {
    const call = callRef.current;
    if (!call || statusRef.current !== "prejoin" || deviceOperationRef.current) return;
    const generation = startGenerationRef.current;
    deviceOperationRef.current = true;
    setIsCheckingDevices(true);
    cameraAvailableRef.current = true;
    try {
      const targetDeviceId = deviceId || cameras[0]?.deviceId;
      if (!targetDeviceId) throw new Error("No default camera available");
      await call.setInputDevicesAsync({ videoDeviceId: targetDeviceId });
      if (generation !== startGenerationRef.current) return;
      const video = call.participants()?.local?.tracks?.video;
      if (video?.state === "blocked" || (video && !video.track && !video.persistentTrack) || !cameraAvailableRef.current) throw new Error("Camera blocked");
      setSelectedCameraId(deviceId);
      saveDevicePrefs({ camera: deviceId });
      cameraAvailableRef.current = true;
      setCameraError("");
      syncTracks();
    } catch {
      if (generation === startGenerationRef.current) {
        cameraAvailableRef.current = false;
        setCameraError(t("无法切换到所选摄像头，请尝试其他设备。", "Could not switch to the selected camera. Try another device."));
      }
    } finally {
      if (generation === startGenerationRef.current) {
        deviceOperationRef.current = false;
        setIsCheckingDevices(false);
      }
    }
  }, [cameras, syncTracks, t]);

  const selectMicrophone = useCallback(async (deviceId: string) => {
    const call = callRef.current;
    if (!call || statusRef.current !== "prejoin" || deviceOperationRef.current) return;
    const generation = startGenerationRef.current;
    deviceOperationRef.current = true;
    setIsCheckingDevices(true);
    try {
      await call.setInputDevicesAsync({ audioDeviceId: deviceId || "default" });
      if (generation !== startGenerationRef.current) return;
      setSelectedMicrophoneId(deviceId);
      saveDevicePrefs({ microphone: deviceId });
      syncTracks();
    } catch {
      if (generation === startGenerationRef.current) {
        setErrorMessage(t("无法切换到所选麦克风，请尝试其他设备。", "Could not switch to the selected microphone. Try another device."));
      }
    } finally {
      if (generation === startGenerationRef.current) {
        deviceOperationRef.current = false;
        setIsCheckingDevices(false);
      }
    }
  }, [syncTracks, t]);

  const selectSpeaker = useCallback(async (deviceId: string) => {
    const call = callRef.current;
    if (!call || statusRef.current !== "prejoin" || deviceOperationRef.current) return;
    const generation = startGenerationRef.current;
    deviceOperationRef.current = true;
    setIsCheckingDevices(true);
    try {
      await call.setOutputDeviceAsync({ outputDeviceId: deviceId || "default" });
      if (generation !== startGenerationRef.current) return;
      setSelectedSpeakerId(deviceId);
      saveDevicePrefs({ speaker: deviceId });
    } catch {
      if (generation === startGenerationRef.current) {
        setErrorMessage(t("无法切换到所选扬声器，请尝试其他设备。", "Could not switch to the selected speaker. Try another device."));
      }
    } finally {
      if (generation === startGenerationRef.current) {
        deviceOperationRef.current = false;
        setIsCheckingDevices(false);
      }
    }
  }, [t]);

  const clearError = useCallback(() => {
    setErrorMessage("");
  }, []);

  const toggleSubtitles = useCallback(() => {
    setShowSubtitles((prev) => !prev);
  }, []);

  const clearTranscripts = useCallback(() => {
    updateTranscripts(() => []);
    setActiveSubtitle(null);
  }, [updateTranscripts]);

  useEffect(() => {
    return () => {
      startGenerationRef.current += 1;
      startingRef.current = false;
      joiningRef.current = false;
      const conversationId = conversationIdRef.current;
      conversationIdRef.current = "";
      teardownCall();
      endConversationUpstream(conversationId);
      notifyConversationEnded(conversationId);
    };
  }, [endConversationUpstream, notifyConversationEnded, teardownCall]);

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
    isPalSpeaking,
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
    localVideoTrack,
    localScreenTrack,
    remoteVideoTrack,
    remoteAudioTrack,
    remoteScreenAudioTrack,
    cameras,
    microphones,
    speakers,
    selectedCameraId,
    selectedMicrophoneId,
    selectedSpeakerId,
    cameraError,
    isCheckingDevices,
    retryCamera,
    selectCamera,
    selectMicrophone,
    selectSpeaker,
    start,
    join,
    cancelPrejoin,
    leave,
    clearError,
  };
}
