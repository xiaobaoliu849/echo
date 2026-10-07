import { useState } from "react";
import type { CoachFeedback, CoachIssue, LearningItemKind } from "../../api";

type Translator = (zh: string, en: string) => string;

export type CoachSaveHandler = (item: {
  text: string;
  kind: LearningItemKind;
  meaning?: string;
  context?: string;
  sourceFeedbackId?: number;
}) => Promise<void>;

type SaveState = "saving" | "saved" | "error";

type Props = {
  feedback: CoachFeedback;
  t: Translator;
  onDismiss?: (id: number) => void;
  onSave?: CoachSaveHandler;
};

function issueLabel(type: CoachIssue["type"], t: Translator): string {
  switch (type) {
    case "grammar":
      return t("语法", "Grammar");
    case "word_choice":
      return t("用词", "Word choice");
    case "fluency":
      return t("流利度", "Fluency");
    case "pronunciation":
      return t("发音", "Pronunciation");
    default:
      return t("地道表达", "Naturalness");
  }
}

export default function CoachFeedbackCard({ feedback, t, onDismiss, onSave }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [saveStates, setSaveStates] = useState<Record<string, SaveState>>({});

  const save = (key: string, item: Parameters<CoachSaveHandler>[0]) => {
    if (!onSave || saveStates[key] === "saving" || saveStates[key] === "saved") return;
    setSaveStates((prev) => ({ ...prev, [key]: "saving" }));
    onSave({ ...item, sourceFeedbackId: feedback.id > 0 ? feedback.id : undefined }).then(
      () => setSaveStates((prev) => ({ ...prev, [key]: "saved" })),
      () => setSaveStates((prev) => ({ ...prev, [key]: "error" }))
    );
  };

  const saveButton = (key: string, item: Parameters<CoachSaveHandler>[0], label: string) => {
    if (!onSave) return null;
    const state = saveStates[key];
    return (
      <button
        type="button"
        className={`vsCoachSave${state === "saved" ? " saved" : ""}`}
        onClick={() => save(key, item)}
        disabled={state === "saving" || state === "saved"}
        aria-label={label}
        title={label}
      >
        {state === "saved"
          ? t("✓ 已收藏", "✓ Saved")
          : state === "saving"
          ? "…"
          : state === "error"
          ? t("重试收藏", "Retry")
          : t("＋ 收藏", "＋ Save")}
      </button>
    );
  };
  const improve = feedback.verdict === "improve";
  const hasDetails = feedback.issues.length > 0 || feedback.vocabulary.length > 0 || Boolean(feedback.tip);

  return (
    <div className={`vsCoachCard ${improve ? "improve" : "good"}`}>
      <button
        type="button"
        className="vsCoachSummary"
        onClick={() => hasDetails && setExpanded((prev) => !prev)}
        aria-expanded={hasDetails ? expanded : undefined}
        disabled={!hasDetails}
      >
        <span className="vsCoachBadge">{improve ? t("💡 口语教练", "💡 Coach") : t("✓ 表达自然", "✓ Natural")}</span>
        {improve && feedback.corrected ? (
          <span className="vsCoachCorrected">{feedback.corrected}</span>
        ) : (
          <span className="vsCoachCorrected muted">{feedback.tip || t("这句说得很好", "Well said")}</span>
        )}
        {hasDetails ? <span className={`vsCoachArrow ${expanded ? "open" : ""}`}>▾</span> : null}
      </button>

      {expanded ? (
        <div className="vsCoachDetails">
          {feedback.issues.map((issue, idx) => (
            <div key={`issue-${idx}`} className="vsCoachIssue">
              <span className="vsCoachIssueType">{issueLabel(issue.type, t)}</span>
              <span className="vsCoachIssueChange">
                {issue.original ? <del>{issue.original}</del> : null}
                {issue.original ? " → " : null}
                <ins>{issue.suggestion}</ins>
              </span>
              {issue.explanation ? <span className="vsCoachIssueWhy">{issue.explanation}</span> : null}
            </div>
          ))}
          {improve && feedback.corrected ? (
            <div className="vsCoachVocab">
              <span className="vsCoachIssueType">{t("正确说法", "Corrected sentence")}</span>
              {saveButton(
                "sentence",
                { text: feedback.corrected, kind: "sentence", context: feedback.user_text },
                t("收藏这句改正，加入复习", "Save this correction for review")
              )}
            </div>
          ) : null}
          {feedback.vocabulary.length > 0 ? (
            <div className="vsCoachVocab">
              <span className="vsCoachIssueType">{t("可以学的表达", "Useful phrases")}</span>
              {feedback.vocabulary.map((item, idx) => (
                <span key={`vocab-${idx}`} className="vsCoachVocabItem" title={item.meaning}>
                  <strong>{item.term}</strong>
                  {item.meaning ? ` · ${item.meaning}` : ""}
                  {saveButton(
                    `vocab-${idx}`,
                    { text: item.term, kind: "phrase", meaning: item.meaning, context: feedback.corrected || feedback.user_text },
                    t(`收藏「${item.term}」`, `Save "${item.term}"`)
                  )}
                </span>
              ))}
            </div>
          ) : null}
          {improve && feedback.tip ? <div className="vsCoachTip">{feedback.tip}</div> : null}
          {onDismiss && feedback.id > 0 ? (
            <button type="button" className="vsCoachDismiss" onClick={() => onDismiss(feedback.id)}>
              {t("识别有误 / 不准确，移除这条", "Misheard or wrong — remove")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
