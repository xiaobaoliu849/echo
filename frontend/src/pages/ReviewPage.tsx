import { useCallback, useEffect, useRef, useState } from "react";
import { Trash2, Volume2 } from "lucide-react";
import {
  deleteLearningItem,
  fetchDueReviews,
  fetchLearningItems,
  fetchSpeakAudio,
  submitReview,
  type LearningItem,
  type LearningStats,
} from "../api";
import { useI18n } from "../i18n";
import "./ReviewPage.css";

const EDGE_VOICES: Record<string, string> = {
  English: "en-US-AvaNeural",
  Japanese: "ja-JP-NanamiNeural",
  Korean: "ko-KR-SunHiNeural",
  French: "fr-FR-DeniseNeural",
  German: "de-DE-KatjaNeural",
  Spanish: "es-ES-ElviraNeural",
};

const EMPTY_STATS: LearningStats = {
  total_items: 0,
  due_now: 0,
  learned_items: 0,
  reviewed_today: 0,
  recalled_today: 0,
};

function formatDue(dueAt: string, t: (zh: string, en: string) => string): string {
  const diffMs = new Date(dueAt).getTime() - Date.now();
  if (Number.isNaN(diffMs) || diffMs <= 0) return t("待复习", "Due now");
  const days = Math.ceil(diffMs / 86_400_000);
  return t(`${days} 天后`, days === 1 ? "in 1 day" : `in ${days} days`);
}

export default function ReviewPage() {
  const { t } = useI18n();
  const [queue, setQueue] = useState<LearningItem[]>([]);
  const [items, setItems] = useState<LearningItem[]>([]);
  const [stats, setStats] = useState<LearningStats>(EMPTY_STATS);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  // Bumped on every stop/new request so a slow TTS response can't start
  // playing after the learner moved on or left the page.
  const playbackGenRef = useRef(0);

  const current = queue[0] ?? null;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [due, all] = await Promise.all([fetchDueReviews(50), fetchLearningItems()]);
      setQueue(due.items);
      setStats(due.stats);
      setItems(all);
      setRevealed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stopAudio = useCallback(() => {
    playbackGenRef.current += 1;
    audioRef.current?.pause();
    audioRef.current = null;
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setSpeaking(false);
  }, []);

  useEffect(() => stopAudio, [stopAudio]);

  const speak = useCallback(
    async (item: LearningItem) => {
      stopAudio();
      const generation = playbackGenRef.current;
      setSpeaking(true);
      try {
        const res = await fetchSpeakAudio({
          text: item.text,
          engine: "edge",
          voice: EDGE_VOICES[item.language] || EDGE_VOICES.English,
        });
        if (generation !== playbackGenRef.current) return;
        const url = URL.createObjectURL(res.blob);
        audioUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = stopAudio;
        audio.onerror = stopAudio;
        await audio.play();
      } catch (err) {
        if (generation !== playbackGenRef.current) return;
        stopAudio();
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [stopAudio]
  );

  const grade = useCallback(
    async (result: "again" | "good") => {
      if (!current || submitting) return;
      const graded = current;
      setSubmitting(true);
      setError("");
      try {
        // A stale result means the card was already graded (e.g. a retry after
        // a lost response); either way it leaves the queue without re-grading.
        const res = await submitReview(graded.id, result, graded.review_count);
        setStats(res.stats);
        setItems((prev) => prev.map((item) => (item.id === res.item.id ? res.item : item)));
        // Remove by id: the queue may have changed (e.g. a delete) while waiting.
        setQueue((prev) => prev.filter((item) => item.id !== graded.id));
        setRevealed(false);
        stopAudio();
        const remaining = queue.filter((item) => item.id !== graded.id).length;
        if (remaining === 0 && res.stats.due_now > 0) {
          // The first batch is capped; fetch the rest instead of claiming "done".
          const next = await fetchDueReviews(50);
          setQueue(next.items);
          setStats(next.stats);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSubmitting(false);
      }
    },
    [current, queue, submitting, stopAudio]
  );

  const remove = useCallback(async (id: number) => {
    try {
      await deleteLearningItem(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
      setQueue((prev) => prev.filter((item) => item.id !== id));
      setStats((prev) => ({ ...prev, total_items: Math.max(0, prev.total_items - 1) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (!current || (target instanceof Element && target.closest("input, textarea, select, button"))) return;
      if (!revealed && (event.key === " " || event.key === "Enter")) {
        event.preventDefault();
        setRevealed(true);
      } else if (revealed && event.key === "1") {
        void grade("again");
      } else if (revealed && event.key === "2") {
        void grade("good");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, revealed, grade]);

  const renderPrompt = (item: LearningItem) => {
    if (item.kind === "sentence") {
      return (
        <>
          <div className="vsReviewPromptLabel">{t("改正这句话，并大声说出来", "Fix this sentence, then say it aloud")}</div>
          <div className="vsReviewPromptText">{item.context || item.text}</div>
        </>
      );
    }
    if (item.meaning) {
      return (
        <>
          <div className="vsReviewPromptLabel">
            {t(`用 ${item.language} 怎么说？说出来再看答案`, `How do you say this in ${item.language}? Say it, then check`)}
          </div>
          <div className="vsReviewPromptText">{item.meaning}</div>
        </>
      );
    }
    return (
      <>
        <div className="vsReviewPromptLabel">{t("回忆它的意思，并用它造一个句子", "Recall its meaning and use it in a sentence")}</div>
        <div className="vsReviewPromptText">{item.text}</div>
      </>
    );
  };

  return (
    <div className="vsReviewPage">
      <header className="vsReviewHeader">
        <h1>{t("复习", "Review")}</h1>
        <p>{t("从口语教练里收藏的表达，按 1 / 3 / 7 / 14 / 30 天间隔复习", "Phrases saved from the speaking coach, reviewed at 1 / 3 / 7 / 14 / 30-day intervals")}</p>
      </header>

      <div className="vsReviewStats">
        <div><strong>{stats.due_now}</strong><span>{t("待复习", "Due")}</span></div>
        <div><strong>{stats.reviewed_today}</strong><span>{t("今日已复习", "Reviewed today")}</span></div>
        <div><strong>{stats.learned_items}</strong><span>{t("已掌握", "Learned")}</span></div>
        <div><strong>{stats.total_items}</strong><span>{t("已收藏", "Saved")}</span></div>
      </div>

      {error ? <div className="vsReviewError" role="alert">{error}</div> : null}

      {loading ? (
        <div className="vsReviewEmpty">{t("加载中…", "Loading…")}</div>
      ) : current ? (
        <section className="vsReviewCard" aria-live="polite">
          <div className="vsReviewProgress">
            {t(`还剩 ${queue.length} 张`, `${queue.length} left`)}
          </div>
          {renderPrompt(current)}
          {revealed ? (
            <div className="vsReviewAnswer">
              <div className="vsReviewAnswerText">
                {current.text}
                <button
                  type="button"
                  className="vsReviewSpeak"
                  onClick={() => void speak(current)}
                  disabled={speaking}
                  aria-label={t("播放发音", "Play pronunciation")}
                  title={t("播放发音", "Play pronunciation")}
                >
                  <Volume2 size={16} />
                </button>
              </div>
              {current.kind === "phrase" && current.meaning ? (
                <div className="vsReviewAnswerMeta">{current.meaning}</div>
              ) : null}
              {current.kind === "phrase" && current.context ? (
                <div className="vsReviewAnswerMeta">{t("例句：", "Example: ")}{current.context}</div>
              ) : null}
              <div className="vsReviewGrade">
                <button type="button" className="again" onClick={() => void grade("again")} disabled={submitting}>
                  {t("没记住", "Again")} <kbd>1</kbd>
                </button>
                <button type="button" className="good" onClick={() => void grade("good")} disabled={submitting}>
                  {t("记住了", "Got it")} <kbd>2</kbd>
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="vsReviewReveal" onClick={() => setRevealed(true)}>
              {t("显示答案", "Show answer")} <kbd>{t("空格", "Space")}</kbd>
            </button>
          )}
        </section>
      ) : (
        <div className="vsReviewEmpty">
          {stats.total_items === 0
            ? t(
                "还没有收藏。在语音通话里打开「🎓 口语教练」，点纠错卡片里的「＋ 收藏」就能加进来。",
                "Nothing saved yet. Turn on 🎓 Speaking coach in a voice call and press ＋ Save on a feedback card."
              )
            : t("今天的复习都完成了，明天再来！", "All caught up for today. Come back tomorrow!")}
        </div>
      )}

      {items.length > 0 ? (
        <section className="vsReviewList">
          <button
            type="button"
            className="vsReviewListToggle"
            onClick={() => setShowAll((prev) => !prev)}
            aria-expanded={showAll}
          >
            {t(`全部收藏（${items.length}）`, `All saved (${items.length})`)} <span className={showAll ? "open" : ""}>▾</span>
          </button>
          {showAll ? (
            <ul>
              {items.map((item) => (
                <li key={item.id}>
                  <div className="vsReviewListMain">
                    <span className="vsReviewListText">{item.text}</span>
                    {item.meaning ? <span className="vsReviewListMeaning">{item.meaning}</span> : null}
                  </div>
                  <span className="vsReviewListDue">{formatDue(item.due_at, t)}</span>
                  <button
                    type="button"
                    className="vsReviewListDelete"
                    onClick={() => void remove(item.id)}
                    aria-label={t(`删除「${item.text}」`, `Delete "${item.text}"`)}
                    title={t("删除", "Delete")}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
