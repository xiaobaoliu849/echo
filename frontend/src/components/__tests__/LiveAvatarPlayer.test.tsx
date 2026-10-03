import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LiveAvatarPlayer from "../LiveAvatarPlayer";

describe("LiveAvatarPlayer live captions", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  });

  it("shows the assistant reply as a caption with the avatar name", () => {
    render(
      <LiveAvatarPlayer
        stream={new EventTarget()}
        avatarName="Leo"
        isVoiceActive
        isAssistantSpeaking
        assistantReply="I can definitely help with UI design ideas!"
      />
    );
    const caption = screen.getByText("I can definitely help with UI design ideas!");
    expect(caption).toBeInTheDocument();
    expect(screen.getByText("Leo", { selector: ".vsAvatarCaptionSpeaker" })).toBeInTheDocument();
    expect(caption.closest(".vsAvatarCaptionLine")).toHaveClass("assistant");
  });

  it("falls back to the user transcript and marks interim results", () => {
    render(
      <LiveAvatarPlayer
        stream={new EventTarget()}
        avatarName="Ben"
        isVoiceActive
        isUserSpeaking
        userTranscript="Hello, can you"
        userTranscriptInterim
      />
    );
    const line = screen.getByText("Hello, can you").closest(".vsAvatarCaptionLine");
    expect(line).toHaveClass("user");
    expect(line).toHaveClass("interim");
  });

  it("toggles captions off and on with the CC button", () => {
    render(
      <LiveAvatarPlayer
        stream={new EventTarget()}
        avatarName="Ben"
        isVoiceActive
        isAssistantSpeaking
        assistantReply="Some reply text"
      />
    );
    expect(screen.getByText("Some reply text")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("实时字幕"));
    expect(screen.queryByText("Some reply text")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("实时字幕"));
    expect(screen.getByText("Some reply text")).toBeInTheDocument();
  });

  it("keeps the original video without a synthetic blurred backdrop", () => {
    const { container } = render(
      <LiveAvatarPlayer stream={new EventTarget()} avatarName="Ben" isVoiceActive />
    );
    expect(container.querySelector(".vsAvatarBackdrop")).toBeNull();
    expect(container.querySelector("video")).toBeInTheDocument();
  });

  it("prioritizes the user's interim transcript over a lingering assistant reply (barge-in)", () => {
    render(
      <LiveAvatarPlayer
        stream={new EventTarget()}
        avatarName="Ben"
        isVoiceActive
        isAssistantSpeaking
        assistantReply="Stale reply from the interrupted turn"
        userTranscript="Wait, I want to ask"
        userTranscriptInterim
      />
    );
    expect(screen.getByText("Wait, I want to ask")).toBeInTheDocument();
    expect(screen.queryByText("Stale reply from the interrupted turn")).not.toBeInTheDocument();
  });

  it("renders free-text names as text and never as CSS classes", () => {
    const { container } = render(
      <LiveAvatarPlayer stream={new EventTarget()} avatarName="John Doe" />
    );
    expect(screen.getByText("John Doe")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("preset-john");
  });
});
