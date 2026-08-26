import goldMark from "../assets/evermind-mark-gold.svg";
import lightMark from "../assets/evermind-mark-light.svg";
import { useI18n } from "../i18n";

type Props = {
  variant?: "gold" | "light";
  compact?: boolean;
  className?: string;
};

export default function EvermindBadge({
  variant = "light",
  compact = false,
  className = "",
}: Props) {
  const { t } = useI18n();
  const source = variant === "gold" ? goldMark : lightMark;

  return (
    <div className={`vsEvermindBadge ${compact ? "compact" : ""} is-${variant} ${className}`.trim()}>
      <img
        className="vsEvermindBadgeMark"
        src={source}
        alt={t("EverMind 标识", "EverMind logo")}
      />
      <div className="vsEvermindBadgeCopy">
        <span className="vsEvermindBadgeEyebrow">{t("长期记忆引擎", "Long-term memory engine")}</span>
        <strong>EverMind</strong>
        {compact ? null : (
          <p>
            {t(
              "为 Echo 的跨会话记忆与上下文延续提供底层能力。",
              "Powers Echo with cross-session memory and context continuity.",
            )}
          </p>
        )}
      </div>
    </div>
  );
}
