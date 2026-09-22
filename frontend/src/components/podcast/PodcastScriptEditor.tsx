import type { UseAudioOverviewResult } from "../../hooks/useAudioOverview";
import { useI18n } from "../../i18n";

type Props = {
  audioOverview: UseAudioOverviewResult;
};

export default function PodcastScriptEditor({ audioOverview }: Props) {
  const { t } = useI18n();
  if (!audioOverview.audioOverviewScriptLines.length) {
    return null;
  }

  return (
    <div className="vsPodcastStepCard">
      <div className="vsPodcastStepHeader">
        <div className="vsPodcastStepTitle">
          <h3>{t("编辑播客脚本", "Edit podcast script")}</h3>
        </div>
        <div className="vsPodcastToolbar">
          <button
            type="button"
            className="vsBtnGhost vsBtnSmall"
            title={t("保存脚本", "Save script")}
            aria-label={t("保存脚本", "Save script")}
            onClick={() => void audioOverview.onSaveScript()}
            disabled={
              audioOverview.audioOverviewSaving ||
              audioOverview.audioOverviewBusy ||
              audioOverview.audioOverviewSynthBusy
            }
          >
            {t("保存", "Save")}
          </button>
          <button
            type="button"
            className="vsBtnGhost vsBtnSmall"
            title={t("复制脚本", "Copy script")}
            aria-label={t("复制脚本", "Copy script")}
            onClick={() => void audioOverview.onCopyScript()}
          >
            {t("复制", "Copy")}
          </button>
          <button
            type="button"
            className="vsBtnGhost vsBtnSmall"
            title={t("导出脚本", "Export script")}
            aria-label={t("导出脚本", "Export script")}
            onClick={audioOverview.onExportScript}
          >
            {t("导出 TXT", "Export TXT")}
          </button>
        </div>
      </div>
      <div className="vsPodcastStepContent">
        <div className="scriptLineBox">
          {audioOverview.audioOverviewScriptLines.map((line, index) => (
            <div
              key={`line-${index}`}
              className={`vsScriptBubble ${line.role === "B" ? "roleB" : "roleA"}`}
            >
              <div className="vsScriptBubbleMeta">
                <select
                  aria-label={t(`第 ${index + 1} 句的主播`, `Speaker for line ${index + 1}`)}
                  className="vsRoleSelect"
                  value={line.role}
                  onChange={(e) => audioOverview.onLineRoleChange(index, e.target.value)}
                >
                  <option value="A">{t("主播 A", "Host A")}</option>
                  <option value="B">{t("主播 B", "Host B")}</option>
                </select>
                <button
                  type="button"
                  className="vsRemoveLineBtn"
                  title={t("删除这条台词", "Delete this line")}
                  onClick={() => audioOverview.onRemoveLine(index)}
                >
                  ×
                </button>
              </div>
              <textarea
                aria-label={t(`第 ${index + 1} 句台词`, `Script line ${index + 1}`)}
                className="vsScriptBubbleInput"
                rows={3}
                value={line.text}
                onChange={(e) => audioOverview.onLineTextChange(index, e.target.value)}
                placeholder={t("输入这一句台词内容", "Enter this line")}
              />
            </div>
          ))}
        </div>
        <div className="vsAddLineCenter">
          <button type="button" className="vsAddLineBtn" onClick={audioOverview.onAddLine}>
            <span className="vsBtnGlyph">+</span>
            {t("添加台词", "Add line")}
          </button>
        </div>
      </div>
    </div>
  );
}
