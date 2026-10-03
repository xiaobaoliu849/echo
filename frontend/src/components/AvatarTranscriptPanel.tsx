import { useEffect, useRef } from "react";
import type { ChatMessage } from "../api";
import { useI18n } from "../i18n";

interface Props {
  messages: ChatMessage[];
  userTranscript: string;
  interim: boolean;
  assistantReply: string;
  avatarName: string;
}

/** A bounded transcript pane: growing text never participates in portrait sizing. */
export default function AvatarTranscriptPanel({ messages, userTranscript, interim, assistantReply, avatarName }: Props) {
  const { t } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const userRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const pane = scrollRef.current;
    if (!pane || !followRef.current) return;
    if (interim && userRef.current) {
      // Keep new speech visible even while the previous assistant reply lingers.
      const row = userRef.current.getBoundingClientRect();
      const viewport = pane.getBoundingClientRect();
      pane.scrollTop += row.height > pane.clientHeight - 24
        ? row.bottom - viewport.bottom + 12
        : row.top - viewport.top - 12;
    } else {
      pane.scrollTop = pane.scrollHeight;
    }
  }, [messages, userTranscript, interim, assistantReply]);
  const turn = (role: string, text: string, key: string, provisional = false) => (
    <div key={key} ref={key === "current-user" ? userRef : undefined} className={`vsAvatarTranscriptTurn ${role} ${provisional ? "interim" : ""}`}>
      <div className="vsAvatarTranscriptSpeaker">
        <strong>{role === "user" ? t("你", "You") : avatarName}</strong>
        {provisional && <span>{t("正在转写…", "Transcribing…")}</span>}
      </div>
      <p>{text}</p>
    </div>
  );
  return (
    <section className="vsAvatarTranscriptPanel vsCallTranscript" aria-label={t("通话转写", "Call transcript")}>
      <div className="vsAvatarTranscriptHeading vsCallTranscriptHeading">{t("实时转写", "Live transcript")}</div>
      <div ref={scrollRef} className="vsAvatarTranscriptScroll vsCallTranscriptScroll" tabIndex={0}
        aria-label={t("滚动查看通话转写", "Scroll call transcript")}
        onScroll={() => {
          const pane = scrollRef.current;
          if (pane) {
            const nearBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 48;
            const row = userRef.current?.getBoundingClientRect();
            const viewport = pane.getBoundingClientRect();
            const atPreview = row && (row.height > pane.clientHeight - 24
              ? Math.abs(row.bottom - viewport.bottom + 12) < 48
              : row.top >= viewport.top && row.top < viewport.top + 48);
            followRef.current = nearBottom || Boolean(interim && atPreview);
          }
        }}>
        {messages.filter(message => message.content && (message.role === "user" || message.role === "assistant"))
          .map((message, index) => turn(message.role, message.content, message.id ?? `completed-${index}`))}
        {userTranscript && turn("user", userTranscript, "current-user", interim)}
        {assistantReply && turn("assistant", assistantReply, "current-assistant")}
        {!messages.length && !userTranscript && !assistantReply && (
          <p className="vsAvatarTranscriptEmpty">{t("直接开始说话，你的话和回复会显示在这里。", "Start speaking. Your words and replies will appear here.")}</p>
        )}
      </div>
    </section>
  );
}
