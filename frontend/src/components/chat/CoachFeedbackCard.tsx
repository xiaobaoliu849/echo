import { useState } from "react";
import type { CoachFeedback, CoachIssue } from "../../api";

type Translator = (zh: string, en: string) => string;

type Props = {
  feedback: CoachFeedback;
  t: Translator;
  onDismiss?: (id: number) => void;
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

export default function CoachFeedbackCard({ feedback, t, onDismiss }: Props) {
  const [expanded, setExpanded] = useState(false);
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
          {feedback.vocabulary.length > 0 ? (
            <div className="vsCoachVocab">
              <span className="vsCoachIssueType">{t("可以学的表达", "Useful phrases")}</span>
              {feedback.vocabulary.map((item, idx) => (
                <span key={`vocab-${idx}`} className="vsCoachVocabItem" title={item.meaning}>
                  <strong>{item.term}</strong>
                  {item.meaning ? ` · ${item.meaning}` : ""}
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
