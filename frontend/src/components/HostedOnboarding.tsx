import { useState } from "react";
import echoIcon from "../assets/echo-icon.png";
import { saveHostedPrefs, type HostedPrefs } from "../api";
import { getHostedLanguage } from "../hosted";
import { hostedErrorMessage } from "../hostedFormat";
import { applyHostedPrefs } from "../hostedPrefs";
import { createInlineTranslator } from "../i18n";

type Level = HostedPrefs["level"];

/**
 * First-run walkthrough: who is learning and their level become the speaking
 * coach's defaults, so the very first call already fits the learner.
 */
export default function HostedOnboarding({
  prefs,
  noTrial = false,
  onDone,
}: {
  prefs: HostedPrefs;
  /** Signed up, but this device or network already used its free trial. */
  noTrial?: boolean;
  onDone: () => void;
}) {
  const t = createInlineTranslator(getHostedLanguage());
  const [step, setStep] = useState(0);
  const [learner, setLearner] = useState<HostedPrefs["learner"]>(prefs.learner);
  const [level, setLevel] = useState<Level>(prefs.level);
  const [coach, setCoach] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const levels: { value: Level; title: string; hint: string }[] = [
    { value: "beginner", title: t("入门", "Beginner"), hint: t("会一些单词和简单句子", "Knows some words and simple sentences") },
    { value: "intermediate", title: t("中级", "Intermediate"), hint: t("能聊日常话题", "Can chat about everyday topics") },
    { value: "advanced", title: t("高级", "Advanced"), hint: t("想说得更地道", "Wants to sound more natural") },
    ...(learner === "adult"
      ? [{ value: "ielts" as Level, title: t("备考雅思", "IELTS prep"), hint: t("练口语考试", "Practise for the speaking test") }]
      : []),
  ];

  const finish = async (skip: boolean) => {
    setBusy(true);
    setError("");
    try {
      const patch: Partial<HostedPrefs> = skip
        ? { onboarded: true }
        : { learner, level: learner === "child" && level === "ielts" ? "beginner" : level, coach, onboarded: true };
      applyHostedPrefs(await saveHostedPrefs(patch));
      onDone();
    } catch (err) {
      setError(hostedErrorMessage(err, t("保存失败，请再试一次", "Could not save, please try again")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="hostedLogin">
      <section className="hostedLoginCard hostedOnboarding" aria-live="polite">
        <img src={echoIcon} alt="" className="hostedLoginIcon" />
        {noTrial && step === 0 ? (
          <p className="hostedLoginNotice" role="status">
            {t(
              "注册成功。这台设备已经领过新人体验，这次不再赠送免费分钟，充值后就能开始练习。",
              "You are signed up. This device has already had its free trial, so top up to start practising.",
            )}
          </p>
        ) : null}
        <p className="hostedOnboardingStep">{t(`第 ${step + 1} 步，共 3 步`, `Step ${step + 1} of 3`)}</p>

        {step === 0 ? (
          <>
            <h1>{t("谁在学英语？", "Who is learning English?")}</h1>
            <p className="hostedLoginLead">{t("AI 外教会按年龄调整说话方式", "The AI tutor adapts how it talks")}</p>
            <div className="hostedChoiceList">
              <button type="button" className={learner === "child" ? "is-active" : ""} onClick={() => setLearner("child")}>
                <strong>{t("孩子（6–12 岁）", "A child (6–12)")}</strong>
                <span>{t("更简单的词、更多鼓励，聊孩子喜欢的话题", "Simpler words, lots of encouragement, kid-friendly topics")}</span>
              </button>
              <button type="button" className={learner === "adult" ? "is-active" : ""} onClick={() => setLearner("adult")}>
                <strong>{t("大人", "An adult")}</strong>
                <span>{t("日常、工作、旅行、面试都能练", "Daily life, work, travel, interviews")}</span>
              </button>
            </div>
          </>
        ) : null}

        {step === 1 ? (
          <>
            <h1>{t("现在的英语水平？", "Current English level?")}</h1>
            <p className="hostedLoginLead">{t("随时可以在设置里改", "You can change this any time in Settings")}</p>
            <div className="hostedChoiceList">
              {levels.map((item) => (
                <button key={item.value} type="button" className={level === item.value ? "is-active" : ""} onClick={() => setLevel(item.value)}>
                  <strong>{item.title}</strong>
                  <span>{item.hint}</span>
                </button>
              ))}
            </div>
          </>
        ) : null}

        {step === 2 ? (
          <>
            <h1>{t("准备好了！", "All set!")}</h1>
            <p className="hostedLoginLead">
              {t("点输入框右边的电话按钮，就能和 AI 外教开口聊。", "Tap the phone button next to the input box to start talking.")}
            </p>
            <label className="hostedOnboardingCheck">
              <input type="checkbox" checked={coach} onChange={(e) => setCoach(e.target.checked)} />
              <span>
                <strong>{t("开启口语教练", "Turn on the speaking coach")}</strong>
                <small>{t("说错时，AI 外教会在对话里顺便帮你改正", "The tutor gently corrects mistakes as you talk")}</small>
              </span>
            </label>
          </>
        ) : null}

        {error ? <p className="hostedLoginError" role="alert">{error}</p> : null}
        <div className="hostedOnboardingActions">
          {step > 0 ? (
            <button type="button" className="hostedOnboardingBack" onClick={() => setStep(step - 1)} disabled={busy}>
              {t("上一步", "Back")}
            </button>
          ) : (
            <button type="button" className="hostedOnboardingBack" onClick={() => void finish(true)} disabled={busy}>
              {t("跳过", "Skip")}
            </button>
          )}
          {step < 2 ? (
            <button type="button" className="hostedLoginSubmit" onClick={() => setStep(step + 1)}>
              {t("下一步", "Next")}
            </button>
          ) : (
            <button type="button" className="hostedLoginSubmit" onClick={() => void finish(false)} disabled={busy}>
              {busy ? t("保存中…", "Saving…") : t("开始练习", "Start practising")}
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
