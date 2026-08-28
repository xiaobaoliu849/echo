import { useCallback, useEffect, useRef, useState } from "react";
import type { DailyCall, DailyEventObject } from "@daily-co/daily-js";
import { createInlineTranslator, type UiLanguage } from "../i18n";
import type { FormatErrorMessage } from "../utils/errorFormatting";
import { createTavusConversation, endTavusConversation } from "../api";

export type TavusConversationStatus = "idle" | "creating" | "joining" | "connected" | "ended";

type StartParams = {
  palId?: string;
  conversationName?: string;
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
  toggleMute: () => void;
  toggleVideo: () => void;
  attachVideoContainer: (node: HTMLDivElement | null) => void;
  start: (params?: StartParams) => Promise<void>;
  leave: () => void;
  clearError: () => void;
};

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
  const autoLeaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<TavusConversationStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [localAudioLevel, setLocalAudioLevel] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);

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

  const attachVideoContainer = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node;
  }, []);

  const clearAutoLeaveTimer = useCallback(() => {
    if (autoLeaveTimerRef.current) {
      clearTimeout(autoLeaveTimerRef.current);
      autoLeaveTimerRef.current = null;
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
    const call = callRef.current;
    callRef.current = null;
    if (!call) {
      return;
    }
    try {
      call.destroy();
    } catch {
      // The frame may already be gone with the unmounted container.
    }
    setLocalAudioLevel(0);
    setIsMuted(false);
    setIsVideoOff(false);
  }, [clearAutoLeaveTimer]);

  const leave = useCallback(() => {
    const call = callRef.current;
    const conversationId = conversationIdRef.current;
    conversationIdRef.current = "";
    teardownCall();
    if (call) {
      try {
        void call.leave();
      } catch {
        // Leaving an already-dead meeting throws; the destroy above released it.
      }
    }
    endConversationUpstream(conversationId);
    setStatus((prev) => (prev === "idle" ? prev : "ended"));
  }, [endConversationUpstream, teardownCall]);

  const start = useCallback(async (params: StartParams = {}) => {
    if (callRef.current) {
      return;
    }
    setErrorMessage("");
    setStatus("creating");
    try {
      const conversation = await createTavusConversation({
        palId: params.palId,
        conversationName: params.conversationName,
      });
      conversationIdRef.current = conversation.conversation_id;
      setStatus("joining");

      // Dynamic import keeps daily-js (and its WebRTC stack) out of the
      // main bundle; the video page is lazy-loaded on its own. The frame
      // is sized by the .vsPalVideoHost iframe CSS rules.
      const Daily = (await import("@daily-co/daily-js")).default;
      const parent = containerRef.current ?? undefined;
      const frame = parent
        ? Daily.createFrame(parent, {
            showLeaveButton: true,
            showFullscreenButton: true,
            iframeStyle: {
              width: "100%",
              height: "100%",
              border: "0",
            },
          })
        : Daily.createFrame();
      callRef.current = frame;

      frame.on("joined-meeting", () => {
        setStatus("connected");
      });
      frame.on("left-meeting", () => {
        leave();
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
      frame.on("participant-updated", (event: any) => {
        if (event?.participant?.local) {
          if (typeof event.participant.audio === "boolean") {
            setIsMuted(!event.participant.audio);
          }
          if (typeof event.participant.video === "boolean") {
            setIsVideoOff(!event.participant.video);
          }
        }
      });
      frame.on("participant-left", () => {
        const activeCall = callRef.current;
        if (!activeCall) {
          return;
        }
        const remaining = Object.keys(activeCall.participants() || {}).length;
        if (remaining > 0) {
          return;
        }
        clearAutoLeaveTimer();
        autoLeaveTimerRef.current = setTimeout(() => {
          autoLeaveTimerRef.current = null;
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
      setStatus("connected");
    } catch (error) {
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
    }
  }, [clearAutoLeaveTimer, formatErrorMessage, leave, t, teardownCall]);

  const clearError = useCallback(() => {
    setErrorMessage("");
  }, []);

  useEffect(() => {
    return () => {
      const conversationId = conversationIdRef.current;
      conversationIdRef.current = "";
      teardownCall();
      endConversationUpstream(conversationId);
    };
  }, [endConversationUpstream, teardownCall]);

  return {
    status,
    errorMessage,
    localAudioLevel,
    isMuted,
    isVideoOff,
    toggleMute,
    toggleVideo,
    attachVideoContainer,
    start,
    leave,
    clearError,
  };
}
