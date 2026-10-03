import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ScreenShareControl from "./ScreenShareControl";
import { createVoiceChatController } from "../../test/factories";

afterEach(cleanup);
describe("Screen-share controls", () => {
  it.each([false, true])("starts and stops sharing with avatar mode %s", avatar => {
    const voiceChat = createVoiceChatController({ voiceChatLiveAvatar: avatar, voiceChatScreenShareSupported: true, voiceChatConnected: true });
    const { rerender } = render(<ScreenShareControl voiceChat={voiceChat} />);
    fireEvent.click(screen.getByRole("button", { name: "共享屏幕" }));
    expect(voiceChat.voiceChatScreenShare.start).toHaveBeenCalledOnce();
    rerender(<ScreenShareControl voiceChat={{ ...voiceChat, voiceChatScreenShare: { ...voiceChat.voiceChatScreenShare, sharing: true, source: "Lesson" } }} />);
    expect(screen.getByText("正在向模型共享屏幕")).toBeInTheDocument();
    expect(screen.getByText("Lesson")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "停止共享" }));
    expect(voiceChat.voiceChatScreenShare.stop).toHaveBeenCalledOnce();
  });
  it("offers cancellation while selecting and keeps sharing independent of mic mute", () => {
    const voiceChat = createVoiceChatController({ voiceChatScreenShareSupported: true, voiceChatConnected: true, voiceChatMuted: true });
    render(<ScreenShareControl voiceChat={{ ...voiceChat, voiceChatScreenShare: { ...voiceChat.voiceChatScreenShare, pending: true } }} />);
    fireEvent.click(screen.getByRole("button", { name: "取消共享" }));
    expect(voiceChat.voiceChatScreenShare.stop).toHaveBeenCalledOnce();
  });
  it("disables unavailable runtime and connecting sessions", () => {
    const voiceChat = createVoiceChatController({ voiceChatScreenShareSupported: true });
    const { rerender } = render(<ScreenShareControl voiceChat={voiceChat} />);
    expect(screen.getByRole("button", { name: "共享屏幕" })).toBeDisabled();
    rerender(<ScreenShareControl voiceChat={{ ...voiceChat, voiceChatConnected: true, voiceChatScreenShare: { ...voiceChat.voiceChatScreenShare, supported: false } }} />);
    expect(screen.getByRole("button", { name: "共享屏幕" })).toBeDisabled();
    expect(screen.getByText("请使用 Chrome、Edge 或 Electron 桌面版")).toBeInTheDocument();
  });
  it("explains Vercel limitations without offering a broken share button", () => {
    const voiceChat = createVoiceChatController({ voiceChatProvider: "Vercel", voiceChatModel: "google/gemini-3.8-live" });
    render(<ScreenShareControl voiceChat={voiceChat} />);
    expect(screen.getByText(/Vercel 实时通话目前不支持屏幕输入/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("hides the control for other audio models", () => {
    const { container } = render(<ScreenShareControl voiceChat={createVoiceChatController()} />);
    expect(container).toBeEmptyDOMElement();
  });
  it.each([["screen:0:0", "整个屏幕"], ["window:731:0", "所选窗口"]])("shows a readable source name for %s", (source, label) => {
    const voiceChat = createVoiceChatController({ voiceChatScreenShareSupported: true, voiceChatConnected: true });
    render(<ScreenShareControl voiceChat={{ ...voiceChat, voiceChatScreenShare: { ...voiceChat.voiceChatScreenShare, sharing: true, source, error: "连接暂时中断，请重试" } }} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(source)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("连接暂时中断，请重试");
    fireEvent.click(screen.getByRole("button", { name: "停止共享" }));
    expect(voiceChat.voiceChatScreenShare.stop).toHaveBeenCalledOnce();
  });
});
