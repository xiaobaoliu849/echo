import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import VoiceCallSettingsPopover from "./VoiceCallSettingsPopover";
import useVoiceChat from "../hooks/useVoiceChat";

import { PREBUILT_AVATARS } from "./LiveAvatarSettings";

describe("avatar preferences", () => {
  it("includes all 11 Google prebuilt avatars", () => {
    expect(PREBUILT_AVATARS).toEqual([
      "Ben",
      "Leo",
      "Kai",
      "Jay",
      "Paul",
      "Sam",
      "Ingrid",
      "Kira",
      "Vera",
      "Carmen",
      "Piper",
    ]);
  });

  it("allows selecting any prebuilt avatar directly from the dropdown", () => {
    const providers = ["AgentPlatform"];
    const catalog = { AgentPlatform: { defaultModel: "gemini-3.8-live", availableModels: ["gemini-3.8-live"] } };
    function Preferences() {
      const voiceChat = useVoiceChat({ providerOptions: providers, providerModelCatalog: catalog,
        preferredProvider: "AgentPlatform", preferredModel: "gemini-3.8-live-avatar", formatErrorMessage: vi.fn() });
      return <VoiceCallSettingsPopover voiceChat={voiceChat} t={(zh) => zh} />;
    }
    render(<Preferences />);
    fireEvent.click(screen.getByTitle("通话设置"));
    fireEvent.change(screen.getByLabelText("形象"), { target: { value: "Kai" } });
    fireEvent.click(screen.getByText("完成"));
    expect(screen.getByTitle("通话设置")).toHaveTextContent("Kai");
  });

  it("does not claim Ben is selected when another face name is empty, and preserves changes after reopening", () => {
    const providers = ["AgentPlatform"];
    const catalog = { AgentPlatform: { defaultModel: "gemini-3.8-live", availableModels: ["gemini-3.8-live"] } };
    function Preferences() {
      const voiceChat = useVoiceChat({ providerOptions: providers, providerModelCatalog: catalog,
        preferredProvider: "AgentPlatform", preferredModel: "gemini-3.8-live-avatar", formatErrorMessage: vi.fn() });
      return <VoiceCallSettingsPopover voiceChat={voiceChat} t={(zh) => zh} />;
    }
    render(<Preferences />);
    fireEvent.click(screen.getByTitle("通话设置"));
    fireEvent.change(screen.getByLabelText("形象"), { target: { value: "custom" } });
    expect(screen.getByText("完成")).toBeDisabled();
    expect(screen.getByTitle("通话设置")).toHaveTextContent("选择形象");
    fireEvent.change(screen.getByLabelText("预置分身名称"), { target: { value: "Leo" } });
    fireEvent.change(screen.getByLabelText("音色"), { target: { value: "Kore" } });
    fireEvent.change(screen.getByLabelText("口音"), { target: { value: "en-GB" } });
    fireEvent.click(screen.getByText("完成"));
    fireEvent.click(screen.getByTitle("通话设置"));
    expect(screen.getByLabelText("形象")).toHaveValue("Leo");
    expect(screen.getByLabelText("音色")).toHaveValue("Kore");
    expect(screen.getByLabelText("口音")).toHaveValue("en-GB");
  });
});
