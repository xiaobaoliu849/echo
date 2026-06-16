import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createAudioOverviewController } from "../../test/factories";
import PodcastSynthBar from "./PodcastSynthBar";

describe("PodcastSynthBar", () => {
  it("renders synth controls", () => {
    render(<PodcastSynthBar audioOverview={createAudioOverviewController()} />);

    expect(screen.getByRole("button", { name: /合成/ })).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: /Yunxi/ })).toHaveLength(2);
  });

  it("renders advanced synth controls when expanded", () => {
    render(
      <PodcastSynthBar
        audioOverview={createAudioOverviewController({ synthBarAdvancedOpen: true })}
      />
    );

    expect(screen.getByText("拼接策略")).toBeInTheDocument();
    expect(screen.getByText("片头音乐")).toBeInTheDocument();
    expect(screen.getByText("片头风格")).toBeInTheDocument();
    expect(screen.getByText("片头时长（毫秒）")).toBeInTheDocument();
    expect(screen.getByDisplayValue("+0%")).toBeInTheDocument();
  });
});
