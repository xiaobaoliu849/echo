import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createAudioOverviewController } from "../../test/factories";
import PodcastSidebar from "./PodcastSidebar";

describe("PodcastSidebar", () => {
  it("renders recent podcasts and preview empty state", () => {
    render(<PodcastSidebar audioOverview={createAudioOverviewController()} />);

    // We should see the tab buttons
    expect(screen.getByText(/最近记录/)).toBeInTheDocument();
    expect(screen.getByText(/运行详情/)).toBeInTheDocument();

    // Default tab is "history", which shows recent podcasts
    expect(screen.getByText(/播客脚本测试/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "载入" })).toBeInTheDocument();

    // Switch to logs tab
    fireEvent.click(screen.getByText(/运行详情/));

    // Now we should see the logs titles
    expect(screen.getByText("Agent 执行状态")).toBeInTheDocument();
    expect(screen.getByText("检索资料来源")).toBeInTheDocument();
    expect(screen.getByText("最近事件日志")).toBeInTheDocument();
  });

  it("renders agent steps and sources when available", () => {
    render(
      <PodcastSidebar
        audioOverview={createAudioOverviewController({
          audioAgentRunId: 3,
          audioAgentStatus: "draft_ready",
          audioAgentCurrentStep: "persist_draft",
          audioAgentResultProvider: "DashScope",
          audioAgentResultModel: "qwen-plus",
          audioAgentSteps: [
            {
              id: 1,
              run_id: 3,
              step_name: "retrieve",
              status: "completed",
              attempt_index: 1,
              started_at: "",
              finished_at: "",
              meta: {},
              error_code: "",
              error_message: ""
            }
          ],
          audioAgentSources: [
            {
              id: 1,
              run_id: 3,
              source_type: "web_search",
              title: "Research source",
              uri: "https://example.com/research",
              snippet: "用户希望内容更贴近年轻上班族。",
              content: "Fetched research content",
              score: 1,
              meta: { origin: "web_search" },
              created_at: ""
            }
          ],
          audioAgentEvents: [
            {
              id: 1,
              run_id: 3,
              event_type: "draft_created",
              payload: {},
              created_at: "2026-03-19T22:20:00Z"
            }
          ]
        })}
      />
    );

    // Should match either English status or translated status
    expect(screen.getByText(/#3 (draft_ready|草稿已就绪)/)).toBeInTheDocument();
    expect(screen.getByText("检索")).toBeInTheDocument();
    expect(screen.getByText("Research source")).toBeInTheDocument();
    expect(screen.getByText("Fetched research content")).toBeInTheDocument();
    expect(screen.getByText("草稿已生成")).toBeInTheDocument();
  });
});
