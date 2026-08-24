import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useI18n } from "../../i18n";
import { revealSettingsSecret } from "../../api/client";

/** Placeholder the backend returns instead of real credentials in GET /api/settings. */
export const MASKED_SECRET = "__MASKED__";

type Props = {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  className?: string;
  /** api_keys section field, e.g. section="api_keys" secretKey="dashscope_api_key" */
  section?: string;
  secretKey?: string;
  /** custom provider id when the secret lives in custom_providers[].api_key */
  customProviderId?: string;
};

/**
 * Password input whose eye-toggle can reveal MASKED_SECRET placeholders by
 * asking the backend for the real value. Behaviour:
 * - value is a real (non-masked) string: eye toggles password/text as before.
 * - value is __MASKED__: clicking the eye fetches and shows the real value
 *   without pushing it into parent state, so saving right after revealing
 *   still sends the placeholder ("keep existing"). Edits made while revealed
 *   are propagated to the parent immediately; hiding then simply re-cloaks.
 */
export default function SecretInput({
  value,
  onChange,
  placeholder,
  className = "vsInput",
  section,
  secretKey,
  customProviderId,
}: Props) {
  const { t } = useI18n();
  const [plainShown, setPlainShown] = useState(false);
  // Real value fetched from the backend while being revealed; null = not revealed.
  const [revealed, setRevealed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isMasked = value === MASKED_SECRET && revealed === null;
  const inputValue = revealed !== null ? revealed : value;
  const showText = revealed !== null || plainShown;

  const handleToggle = () => {
    if (revealed !== null) {
      setRevealed(null);
      return;
    }
    if (!isMasked) {
      setPlainShown((v) => !v);
      return;
    }
    if (busy) return;
    setBusy(true);
    revealSettingsSecret(section, secretKey, customProviderId)
      .then((real) => setRevealed(real))
      .catch(() => {
        // Keep the masked placeholder on failure; nothing else to do here.
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="vsPasswordFieldWrap">
      <input
        className={className}
        type={showText ? "text" : "password"}
        value={inputValue}
        placeholder={placeholder}
        onFocus={(e) => {
          // Typing over the placeholder should replace it wholesale.
          if (value === MASKED_SECRET) e.target.select();
        }}
        onChange={(e) => {
          if (revealed !== null) setRevealed(e.target.value);
          onChange(e.target.value);
        }}
      />
      <button
        type="button"
        className="vsPasswordToggleBtn"
        onMouseDown={(e) => e.preventDefault()}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          handleToggle();
        }}
        title={showText ? t("隐藏", "Hide") : t("显示", "Show")}
      >
        {showText ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}
