import { useState, useEffect } from "react";
import type { UseAudioOverviewResult } from "../../hooks/useAudioOverview";
import { useI18n } from "../../i18n";

type Props = {
  audioOverview: UseAudioOverviewResult;
};

export default function PodcastSidebar({ audioOverview }: Props) {
  const { t, language } = useI18n();
  const [sidebarTab, setSidebarTab] = useState<"history" | "logs">("history");

  // Auto-switch to logs tab when an agent run starts
  useEffect(() => {
    if (audioOverview.audioAgentRunId !== null) {
      setSidebarTab("logs");
    }
  }, [audioOverview.audioAgentRunId]);

  const formatEventLabel = (eventType: string) => {
    const labels: Record<string, string> = {
      run_created: t("任务已创建", "Run created"),
      step_started: t("步骤开始", "Step started"),
      step_completed: t("步骤完成", "Step completed"),
      retrieval_summary: t("检索完成", "Retrieval completed"),
      research_brief_created: t("研究摘要已生成", "Research brief created"),
      draft_created: t("草稿已生成", "Draft created"),
      podcast_saved: t("草稿已保存", "Draft saved"),
      synthesis_started: t("开始合成", "Synthesis started"),
      synthesis_completed: t("合成完成", "Synthesis completed"),
      run_failed: t("任务失败", "Run failed"),
      execution_deferred: t("等待执行", "Execution deferred")
    };
    return labels[eventType] || eventType;
  };

  const formatStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      queued: t("排队中", "Queued"),
      running: t("执行中", "Running"),
      draft_ready: t("草稿已就绪", "Draft ready"),
      synthesizing: t("合成中", "Synthesizing"),
      completed: t("已完成", "Completed"),
      failed: t("失败", "Failed"),
      completed_step: t("已完成", "Completed")
    };
    return labels[status] || status;
  };

  const formatStepLabel = (stepName: string) => {
    const labels: Record<string, string> = {
      prepare: t("准备", "Prepare"),
      retrieve: t("检索", "Retrieve"),
      assemble_evidence: t("整理资料", "Assemble Evidence"),
      generate_script: t("生成脚本", "Generate Script"),
      persist_draft: t("保存草稿", "Persist Draft"),
      synthesize_audio: t("合成音频", "Synthesize Audio")
    };
    return labels[stepName] || stepName;
  };

  const formatUpdatedAt = (updatedAt: string) => {
    const parsed = new Date(updatedAt);
    if (Number.isNaN(parsed.getTime())) {
      return updatedAt;
    }

    return new Intl.DateTimeFormat(language === "en-US" ? "en-US" : "zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(parsed);
  };

  const isAgentRunning = audioOverview.audioAgentRunId !== null && 
    (audioOverview.audioAgentStatus === "running" || audioOverview.audioAgentStatus === "queued" || audioOverview.audioAgentStatus === "synthesizing");

  return (
    <aside className="vsPodcastSide" style={{ display: "flex", flexDirection: "column", gap: "16px", height: "100%" }}>
      {/* ── Card 1: Synthesis Preview ── */}
      <div className="vsPodcastSideCard" style={{ flexShrink: 0 }}>
        <div className="vsPodcastSideHeader">
          <h3>{t("合成预览", "Synthesis Preview")}</h3>
        </div>
        {audioOverview.audioOverviewAudioUrl ? (
          <div className="audioWrap vsPodcastAudioWrap" style={{ padding: "8px 0" }}>
            <audio controls src={audioOverview.audioOverviewAudioUrl} style={{ width: "100%" }} />
          </div>
        ) : (
          <div 
            className="vsPodcastPreviewEmpty" 
            aria-hidden="true"
            style={{ 
              display: "flex", 
              flexDirection: "column", 
              alignItems: "center", 
              justifyContent: "center", 
              padding: "32px 16px", 
              background: "var(--panel-strong)", 
              borderRadius: "12px", 
              border: "1px dashed var(--line)", 
              color: "var(--muted)",
              gap: "8px"
            }}
          >
            <span style={{ fontSize: "28px" }}>🎧</span>
            <span style={{ fontSize: "12px" }}>{t("等待音频合成...", "Waiting for audio synthesis...")}</span>
          </div>
        )}
      </div>

      {/* ── Card 2: Consolidated Studio Panel ── */}
      <div 
        className="vsPodcastSideCard" 
        style={{ 
          flex: 1, 
          display: "flex", 
          flexDirection: "column", 
          minHeight: 0, 
          paddingBottom: "12px" 
        }}
      >
        {/* Tab Switcher */}
        <div 
          className="vsModeTabs" 
          style={{ 
            display: "flex", 
            gap: "8px", 
            marginBottom: "16px",
            borderBottom: "1px solid var(--line)",
            paddingBottom: "12px",
            flexShrink: 0
          }}
        >
          <button
            type="button"
            className={sidebarTab === "history" ? "vsBtnPrimary" : "vsBtnSecondary"}
            onClick={() => setSidebarTab("history")}
            style={{ flex: 1, height: "34px", fontSize: "12px", borderRadius: "8px" }}
          >
            📁 {t("最近记录", "History")}
          </button>
          <button
            type="button"
            className={sidebarTab === "logs" ? "vsBtnPrimary" : "vsBtnSecondary"}
            onClick={() => setSidebarTab("logs")}
            style={{ 
              flex: 1, 
              height: "34px", 
              fontSize: "12px", 
              borderRadius: "8px",
              position: "relative" 
            }}
          >
            ⚙️ {t("运行详情", "Logs")}
            {isAgentRunning && (
              <span 
                className="pulsing-dot" 
                style={{ 
                  position: "absolute", 
                  top: "6px", 
                  right: "6px", 
                  width: "8px", 
                  height: "8px", 
                  borderRadius: "50%", 
                  backgroundColor: "#10b981",
                  boxShadow: "0 0 8px #10b981"
                }} 
              />
            )}
          </button>
        </div>

        {/* Tab Contents */}
        <div 
          className="custom-scrollbar" 
          style={{ 
            flex: 1, 
            overflowY: "auto", 
            paddingRight: "4px" 
          }}
        >
          {sidebarTab === "history" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div 
                style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "space-between", 
                  marginBottom: "4px",
                  flexShrink: 0
                }}
              >
                <span style={{ fontSize: "11px", fontWeight: "700", color: "var(--muted)", textTransform: "uppercase" }}>
                  {t("最近项目列表", "Recent Projects")}
                </span>
                <button
                  type="button"
                  className="ghost vsPodcastMiniBtn"
                  onClick={() => void audioOverview.onRefreshList()}
                  disabled={audioOverview.audioOverviewListBusy}
                  style={{ fontSize: "11px", padding: "2px 6px" }}
                >
                  {audioOverview.audioOverviewListBusy ? t("刷新中...", "Refreshing...") : t("刷新列表", "Refresh")}
                </button>
              </div>

              <div className="voiceList" style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {audioOverview.audioOverviewPodcasts.map((item) => (
                  <div 
                    key={`podcast-${item.id}`} 
                    className="voiceItem"
                    style={{
                      padding: "10px",
                      background: "var(--panel-strong)",
                      border: "1px solid var(--line)",
                      borderRadius: "8px",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      transition: "all 0.2s"
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0, paddingRight: "8px" }}>
                      <strong 
                        style={{ 
                          display: "block", 
                          fontSize: "13px", 
                          color: "var(--text)", 
                          overflow: "hidden", 
                          textOverflow: "ellipsis", 
                          whiteSpace: "nowrap" 
                        }}
                      >
                        #{item.id} {item.topic}
                      </strong>
                      <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--muted)" }}>
                        {t(
                          `${item.language.toUpperCase()} ｜ ${item.script_lines.length} 句 ｜ `,
                          `${item.language.toUpperCase()} | ${item.script_lines.length} lines | `
                        )}
                        <time dateTime={item.updated_at}>{formatUpdatedAt(item.updated_at)}</time>
                      </p>
                    </div>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => void audioOverview.onLoadPodcast(item.id)}
                      style={{ fontSize: "12px", padding: "4px 8px", minWidth: "48px", flexShrink: 0 }}
                    >
                      {t("载入", "Load")}
                    </button>
                  </div>
                ))}
                {!audioOverview.audioOverviewPodcasts.length ? (
                  <p className="vsInlineEmptyState muted" style={{ textAlign: "center", fontStyle: "italic", fontSize: "12px", padding: "24px 0" }}>
                    {t("暂时还没有播客记录。", "No podcast history yet.")}
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* Agent execution details */}
              <div>
                <h4 style={{ fontSize: "12px", fontWeight: "700", color: "var(--muted)", textTransform: "uppercase", marginBottom: "8px", marginTop: 0 }}>
                  {t("Agent 执行状态", "Agent Execution")}
                </h4>
                {audioOverview.audioAgentRunId !== null ? (
                  <div className="voiceList" style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div 
                      className="voiceItem"
                      style={{
                        padding: "10px",
                        background: "var(--panel-strong)",
                        border: "1px solid var(--line)",
                        borderRadius: "8px"
                      }}
                    >
                      <strong style={{ fontSize: "13px", color: "var(--text)" }}>
                        #{audioOverview.audioAgentRunId} {formatStatusLabel(audioOverview.audioAgentStatus || "queued")}
                      </strong>
                      <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--muted)" }}>
                        {t("当前步骤：", "Current: ")}
                        {formatStepLabel(audioOverview.audioAgentCurrentStep || "prepare")}
                        {audioOverview.audioAgentResultProvider ? ` · ${audioOverview.audioAgentResultProvider}` : ""}
                        {audioOverview.audioAgentResultModel ? ` / ${audioOverview.audioAgentResultModel}` : ""}
                      </p>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", paddingLeft: "4px", borderLeft: "2px solid var(--line)" }}>
                      {audioOverview.audioAgentSteps.map((step) => (
                        <div key={`agent-step-${step.id}`} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "2px 6px" }}>
                          <span style={{ fontSize: "12px", color: "var(--text)" }}>{formatStepLabel(step.step_name)}</span>
                          <span style={{ 
                            fontSize: "10px", 
                            fontWeight: "600",
                            color: step.status === "completed_step" || step.status === "completed" ? "#10b981" : step.status === "failed" ? "#f43f5e" : "var(--muted)" 
                          }}>
                            {formatStatusLabel(step.status)}
                          </span>
                        </div>
                      ))}
                    </div>

                    {audioOverview.audioAgentErrorMessage ? (
                      <div 
                        style={{ 
                          padding: "10px", 
                          background: "#fff1f2", 
                          border: "1px solid #ffe4e6", 
                          borderRadius: "8px", 
                          color: "#b91c1c", 
                          fontSize: "12px",
                          lineHeight: "1.4"
                        }}
                      >
                        <strong>{t("失败信息：", "Failure: ")}</strong>
                        {audioOverview.audioAgentErrorMessage}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="vsInlineEmptyState muted" style={{ fontSize: "12px", fontStyle: "italic", margin: 0 }}>
                    {t("生成脚本后会显示写稿步骤。", "Steps will appear here during generation.")}
                  </p>
                )}
              </div>

              {/* Data Sources */}
              <div style={{ borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
                <h4 style={{ fontSize: "12px", fontWeight: "700", color: "var(--muted)", textTransform: "uppercase", marginBottom: "8px", marginTop: 0 }}>
                  {t("检索资料来源", "Sources")}
                </h4>
                {audioOverview.audioAgentRunId !== null && audioOverview.audioAgentSources.length ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {audioOverview.audioAgentSources.map((source) => (
                      <details 
                        key={`agent-source-${source.id}`}
                        style={{
                          background: "var(--panel-strong)",
                          border: "1px solid var(--line)",
                          borderRadius: "6px",
                          padding: "6px 8px"
                        }}
                      >
                        <summary style={{ cursor: "pointer", fontSize: "12px", fontWeight: "600", outline: "none", color: "var(--text)" }}>
                          {source.title || source.source_type}
                        </summary>
                        <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "4px", lineHeight: "1.4", borderTop: "1px solid var(--line)", paddingTop: "4px" }}>
                          {source.content || source.uri || t("无内容", "No content")}
                        </div>
                      </details>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: "12px", color: "var(--muted)", margin: 0, fontStyle: "italic" }}>
                    {t("暂无来源信息。", "No source information yet.")}
                  </p>
                )}
              </div>

              {/* Recent event logs */}
              <div style={{ borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
                <h4 style={{ fontSize: "12px", fontWeight: "700", color: "var(--muted)", textTransform: "uppercase", marginBottom: "8px", marginTop: 0 }}>
                  {t("最近事件日志", "Events Log")}
                </h4>
                {audioOverview.audioAgentRunId !== null && audioOverview.audioAgentEvents.length ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {audioOverview.audioAgentEvents.slice(-6).reverse().map((event) => (
                      <div 
                        key={`agent-event-${event.id}`}
                        style={{ 
                          fontSize: "11px", 
                          color: "var(--text)", 
                          padding: "6px", 
                          background: "var(--panel-strong)", 
                          borderRadius: "4px",
                          borderLeft: "2px solid var(--brand)"
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", fontWeight: "600", color: "var(--text)" }}>
                          <span>{formatEventLabel(event.event_type)}</span>
                          <span style={{ color: "var(--muted)", fontWeight: "normal" }}>{formatUpdatedAt(event.created_at)}</span>
                        </div>
                        {typeof event.payload.step_name === "string" && (
                          <div style={{ color: "var(--muted)", fontSize: "10px", marginTop: "2px" }}>
                            {formatStepLabel(event.payload.step_name)}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: "12px", color: "var(--muted)", margin: 0, fontStyle: "italic" }}>
                    {t("暂无事件记录。", "No event records yet.")}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
