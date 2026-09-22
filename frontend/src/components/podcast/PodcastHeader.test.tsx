import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createAudioOverviewController } from "../../test/factories";
import PodcastHeader from "./PodcastHeader";

describe("PodcastHeader", () => {
  it("renders Echo branding without technical status badges", () => {
    render(<PodcastHeader audioOverview={createAudioOverviewController()} />);

    expect(screen.getByText("Echo 播客")).toBeInTheDocument();
    expect(screen.queryByText("播客 #12")).not.toBeInTheDocument();
    expect(screen.queryByText("长期记忆未接入")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建草稿" })).toBeInTheDocument();
  });

  it("keeps internal run status out of the header", () => {
    render(
      <PodcastHeader
        audioOverview={createAudioOverviewController({
          audioAgentRunId: 7,
          audioAgentStatus: "draft_ready"
        })}
      />
    );

    expect(screen.queryByText("Agent Run #7 · draft_ready")).not.toBeInTheDocument();
  });

  it("renders delete action when menu is open", () => {
    render(
      <PodcastHeader
        audioOverview={createAudioOverviewController({ audioOverviewMenuOpen: true })}
      />
    );

    expect(screen.getByRole("button", { name: "删除当前" })).toBeInTheDocument();
  });
});
