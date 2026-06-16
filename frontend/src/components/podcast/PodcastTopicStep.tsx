import { PROVIDERS } from "../../appConfig";
import type { UseAudioOverviewResult } from "../../hooks/useAudioOverview";
import { useI18n } from "../../i18n";
import type { MouseEvent } from "react";

type Props = {
  audioOverview: UseAudioOverviewResult;
};

export default function PodcastTopicStep({ audioOverview }: Props) {
  const { t } = useI18n();
  const handleGenerateClick = (event: MouseEvent<HTMLButtonElement>) => {
    void audioOverview.onGenerateScript(
      event as unknown as Parameters<typeof audioOverview.onGenerateScript>[0]
    );
  };

  return (
    <form className="vsPodcastStepCard" onSubmit={audioOverview.onGenerateScript}>
      <div className="vsPodcastStepHeader">
        <div className="vsPodcastStepTitle">
          <span className="vsStepNum">1</span>
          <h3>{t("确定播客主题", "Choose the podcast topic")}</h3>
        </div>
      </div>
      <div className="vsPodcastStepContent">
        <label className="vsPodcastField">
          <span className="vsPodcastFieldLabel">{t("话题", "Topic")}</span>
          <textarea
            className="vsTopicInput"
            rows={5}
            value={audioOverview.audioOverviewTopic}
            onChange={(e) => audioOverview.onTopicChange(e.target.value)}
            placeholder={t("输入你想讨论的话题，例如：AI 如何改变个人学习习惯？", "Enter the topic you want to discuss, for example: How is AI changing personal learning habits?")}
          />
        </label>

        <div className="vsPodcastStepActions">
          <button
            className="vsGenerateBtn"
            type="button"
            onClick={handleGenerateClick}
            disabled={audioOverview.audioOverviewBusy}
          >
            {audioOverview.audioOverviewBusy ? t("生成中...", "Generating...") : t("生成脚本", "Generate script")}
          </button>
          <button
            type="button"
            className="vsPodcastAdvancedToggle"
            onClick={audioOverview.onToggleAdvanced}
          >
            {audioOverview.audioOverviewAdvancedOpen ? t("收起高级设置", "Hide advanced settings") : t("⚙️ 高级设置", "⚙️ Advanced settings")}
          </button>
        </div>

        {audioOverview.audioOverviewAdvancedOpen ? (
          <div className="vsPodcastAdvancedPanel">
            <div className="rowOverview">
              <label>
                {t("语言", "Language")}
                <select
                  value={audioOverview.audioOverviewLanguage}
                  onChange={(e) => audioOverview.onLanguageChange(e.target.value)}
                >
                  <option value="zh">{t("中文", "Chinese")}</option>
                  <option value="en">{t("英文", "English")}</option>
                </select>
              </label>
              <label>
                {t("LLM 供应商", "LLM provider")}
                <select
                  value={audioOverview.audioOverviewProvider}
                  onChange={(e) => audioOverview.onProviderChange(e.target.value)}
                >
                  {PROVIDERS.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("模型", "Model")}
                <input
                  value={audioOverview.audioOverviewModel}
                  onChange={(e) => audioOverview.onModelChange(e.target.value)}
                  placeholder={t("留空则使用默认模型", "Leave blank to use the default model")}
                />
              </label>
              <label>
                {t("对话轮数", "Turn count")}
                <input
                  type="number"
                  min={2}
                  max={40}
                  value={audioOverview.audioOverviewTurnCount}
                  onChange={(e) => audioOverview.onTurnCountChange(e.target.value)}
                />
              </label>
            </div>

            <label className="vsPodcastMemoryToggle">
              <input
                type="checkbox"
              checked={audioOverview.audioOverviewUseMemory}
              onChange={(e) => audioOverview.onUseMemoryChange(e.target.checked)}
            />
            <div>
                <strong>{t("使用 EverMem 长期记忆辅助脚本生成", "Use EverMem long-term memory to assist script generation")}</strong>
                <p>
                  {audioOverview.audioOverviewMemoryConfigured
                    ? t("生成播客脚本时会尝试召回相关历史记忆，并把本次草稿写回 EverMem。", "Podcast generation will try to recall relevant memories and write this draft back to EverMem.")
                    : t("请先在设置页启用 EverMem。未接入时这里不会注入长期记忆。", "Enable EverMem in Settings first. No long-term memory will be injected until then.")}
                </p>
              </div>
            </label>

            {audioOverview.audioOverviewMemoriesRetrieved > 0 || audioOverview.audioOverviewMemorySaved ? (
              <p className="vsPodcastMemoryResult">
                {audioOverview.audioOverviewMemoriesRetrieved > 0
                  ? t(
                    `本次生成已引用 ${audioOverview.audioOverviewMemoriesRetrieved} 条长期记忆。`,
                    `This draft referenced ${audioOverview.audioOverviewMemoriesRetrieved} long-term memories.`
                  )
                  : t("本次生成未召回历史记忆。", "This draft did not recall any previous memories.")}
                {audioOverview.audioOverviewMemorySaved ? t(" 已写入本次播客草稿。", " Saved back into this podcast draft.") : ""}
              </p>
            ) : null}

            <label className="vsPodcastField">
              <span className="vsPodcastFieldLabel">{t("手动资料", "Manual source text")}</span>
              <textarea
                rows={4}
                value={audioOverview.audioAgentSourceText}
                onChange={(e) => audioOverview.onSourceTextChange(e.target.value)}
                placeholder={t(
                  "补充你已经掌握的背景资料、采访提纲、会议纪要或重点观点。",
                  "Add background notes, interview outlines, meeting notes, or key points you already have."
                )}
              />
            </label>

            <label className="vsPodcastField">
              <span className="vsPodcastFieldLabel">{t("来源 URL 列表", "Source URL list")}</span>
              <textarea
                rows={4}
                value={audioOverview.audioAgentSourceUrlsText}
                onChange={(e) => audioOverview.onSourceUrlsTextChange(e.target.value)}
                placeholder={t(
                  "每行一个 URL。Agent 会尝试抓取网页正文；如果没有手动资料，也会尝试自动搜索公开网页。",
                  "One URL per line. The agent will try to fetch page text; without manual sources it will also try public web search."
                )}
              />
            </label>

            <label className="vsPodcastField">
              <span className="vsPodcastFieldLabel">{t("生成约束", "Generation constraints")}</span>
              <textarea
                rows={4}
                value={audioOverview.audioAgentGenerationConstraints}
                onChange={(e) => audioOverview.onGenerationConstraintsChange(e.target.value)}
                placeholder={t(
                  "例如：更像 NotebookLM 风格、避免夸张表述、口语化、控制在 6 分钟内、面向普通用户。",
                  "For example: more like NotebookLM, avoid exaggerated claims, conversational tone, under 6 minutes, for mainstream users."
                )}
              />
            </label>
          </div>
        ) : null}
      </div>
    </form>
  );
}
