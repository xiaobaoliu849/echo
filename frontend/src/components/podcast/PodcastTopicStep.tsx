import { PROVIDERS } from "../../appConfig";
import type { UseAudioOverviewResult } from "../../hooks/useAudioOverview";
import { useI18n } from "../../i18n";

type Props = {
  audioOverview: UseAudioOverviewResult;
};

export default function PodcastTopicStep({ audioOverview }: Props) {
  const { t } = useI18n();

  return (
    <form className="vsPodcastPromptCard" onSubmit={audioOverview.onGenerateScript}>
      <div className="vsPodcastPromptHeader">
        <div>
          <h3 id="podcast-topic-label" className="vsPodcastPromptTitle">{t("确定播客主题", "Choose the podcast topic")}</h3>
          <p className="vsPodcastPromptDesc">
            {t("输入一个话题，生成双人对话脚本。下一步可编辑内容并选择声音。", "Start with a topic. Then review the script and choose voices for your two hosts.")}
          </p>
        </div>
      </div>

      <div className="vsPodcastPromptBody">
        <div className="vsTopicInputWrap">
          <textarea
            aria-labelledby="podcast-topic-label"
            className="vsTopicInput"
            rows={4}
            value={audioOverview.audioOverviewTopic}
            onChange={(e) => audioOverview.onTopicChange(e.target.value)}
            placeholder={t(
              "输入你想讨论的话题，例如：AI 如何改变个人学习习惯？",
              "Enter the topic you want to discuss, for example: How is AI changing personal learning habits?"
            )}
          />

          <div className="vsTopicActionBar">
            <button
              type="button"
              className={`vsBtnGhost vsBtnSmall vsAdvancedBtn ${audioOverview.audioOverviewAdvancedOpen ? "is-open" : ""}`}
              aria-expanded={audioOverview.audioOverviewAdvancedOpen}
              aria-controls="podcast-options"
              onClick={audioOverview.onToggleAdvanced}
            >
              {audioOverview.audioOverviewAdvancedOpen
                ? t("收起设置与资料", "Hide settings & sources")
                : t("设置与参考资料", "Settings & sources")}
            </button>

            <button
              type="submit"
              className="vsBtnPrimary vsGenerateBtn"
              disabled={audioOverview.audioOverviewBusy || !audioOverview.audioOverviewTopic.trim()}
            >
              {audioOverview.audioOverviewBusy ? (
                <>
                  <span className="spinner vsLoadingSpinnerInline" />
                  {t("生成中...", "Generating...")}
                </>
              ) : (
                t("生成脚本", "Generate script")
              )}
            </button>
          </div>
        </div>

        {audioOverview.audioOverviewAdvancedOpen && (
          <div id="podcast-options" className="vsPodcastAdvancedDrawer">
            <div className="vsAdvancedSectionTitle">{t("生成设置", "Generation settings")}</div>

            <div className="vsAdvancedGrid">
              <label className="vsPodcastField">
                <span className="vsPodcastFieldLabel">{t("语言", "Language")}</span>
                <select
                  value={audioOverview.audioOverviewLanguage}
                  onChange={(e) => audioOverview.onLanguageChange(e.target.value)}
                  className="vsInputSelect"
                >
                  <option value="zh">{t("中文", "Chinese")}</option>
                  <option value="en">{t("英文", "English")}</option>
                </select>
              </label>

              <label className="vsPodcastField">
                <span className="vsPodcastFieldLabel">{t("LLM 供应商", "LLM Provider")}</span>
                <select
                  value={audioOverview.audioOverviewProvider}
                  onChange={(e) => audioOverview.onProviderChange(e.target.value)}
                  className="vsInputSelect"
                >
                  {PROVIDERS.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>

              <label className="vsPodcastField">
                <span className="vsPodcastFieldLabel">{t("模型", "Model")}</span>
                <input
                  type="text"
                  value={audioOverview.audioOverviewModel}
                  onChange={(e) => audioOverview.onModelChange(e.target.value)}
                  placeholder={t("留空则使用默认模型", "Leave blank for default model")}
                  className="vsInputText"
                />
              </label>

              <label className="vsPodcastField">
                <span className="vsPodcastFieldLabel">{t("对话轮数", "Turn Count")}</span>
                <input
                  type="number"
                  min={2}
                  max={40}
                  value={audioOverview.audioOverviewTurnCount}
                  onChange={(e) => audioOverview.onTurnCountChange(e.target.value)}
                  className="vsInputText"
                />
              </label>
            </div>

            <div className="vsAdvancedSectionTitle">{t("长期记忆（可选）", "Memory (optional)")}</div>

            <label className="vsPodcastMemoryCard">
              <input
                type="checkbox"
                checked={audioOverview.audioOverviewUseMemory}
                onChange={(e) => audioOverview.onUseMemoryChange(e.target.checked)}
              />
              <div className="vsMemoryCardContent">
                <strong>{t("使用 EverMem 长期记忆辅助脚本生成", "Use EverMem long-term memory to assist script generation")}</strong>
                <p>
                  {audioOverview.audioOverviewMemoryConfigured
                    ? t("系统会自动检索与主题相关的对话记忆，并将本次播客剧本归档至长期记忆库。", "Retrieves related memories and archives this podcast draft into EverMem.")
                    : t("尚未启用 EverMem 模块，可在系统设置中开启。", "EverMem module is not enabled yet. Turn it on in Settings.")}
                </p>
              </div>
            </label>

            {audioOverview.audioOverviewMemoriesRetrieved > 0 || audioOverview.audioOverviewMemorySaved ? (
              <div className="vsPodcastMemoryNotice">
                {audioOverview.audioOverviewMemoriesRetrieved > 0
                  ? t(
                      `💡 本次生成已自动融合 ${audioOverview.audioOverviewMemoriesRetrieved} 条长期记忆。`,
                      `💡 Successfully integrated ${audioOverview.audioOverviewMemoriesRetrieved} long-term memories.`
                    )
                  : t("💡 本次生成未搜索到匹配的记忆片段。", "💡 No matching memory fragments found.")}
                {audioOverview.audioOverviewMemorySaved ? t(" 草稿已同步至记忆库。", " Draft synced to memory bank.") : ""}
              </div>
            ) : null}

            <div className="vsAdvancedSectionTitle">{t("参考资料（可选）", "Sources (optional)")}</div>

            <div className="vsAdvancedGridTwo">
              <label className="vsPodcastField">
                <span className="vsPodcastFieldLabel">{t("手动资料", "Manual source text")}</span>
                <textarea
                  rows={3}
                  value={audioOverview.audioAgentSourceText}
                  onChange={(e) => audioOverview.onSourceTextChange(e.target.value)}
                  placeholder={t("补充已掌握的背景资料、采访提纲或重点笔记...", "Paste background notes, article summaries, or outline...")}
                  className="vsTextareaField"
                />
              </label>

              <label className="vsPodcastField">
                <span className="vsPodcastFieldLabel">{t("来源 URL 列表", "Source URL list")}</span>
                <textarea
                  rows={3}
                  value={audioOverview.audioAgentSourceUrlsText}
                  onChange={(e) => audioOverview.onSourceUrlsTextChange(e.target.value)}
                  placeholder={t("每行填写一个网页链接 (https://...)", "One web URL per line (https://...)")}
                  className="vsTextareaField"
                />
              </label>
            </div>

            <label className="vsPodcastField" style={{ marginTop: "12px" }}>
              <span className="vsPodcastFieldLabel">{t("生成约束", "Generation constraints")}</span>
              <textarea
                rows={2}
                value={audioOverview.audioAgentGenerationConstraints}
                onChange={(e) => audioOverview.onGenerationConstraintsChange(e.target.value)}
                placeholder={t(
                  "例如：对谈口语化、通俗易懂、控制在 5 分钟内、类似 NotebookLM 的自然交流风格。",
                  "E.g.: Conversational tone, beginner-friendly, under 5 minutes, NotebookLM style."
                )}
              />
            </label>
          </div>
        )}
      </div>
    </form>
  );
}
