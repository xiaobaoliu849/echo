import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChatInputBar from "../chat/ChatInputBar";
import useVoiceChat from "../../hooks/useVoiceChat";
import { createChatController, createVoiceChatController } from "../../test/factories";

describe("ChatInputBar", () => {
  it("configures Cloud Avatar through the real hook without an idle stage and returns to audio", () => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    const providerOptions = ["Google", "AgentPlatform"];
    const providerModelCatalog = {
      Google: { availableModels: ["gemini-3.8-live"], enabledModels: ["gemini-3.8-live"], defaultModel: "gemini-3.8-live" },
      AgentPlatform: { availableModels: ["gemini-3.8-live"], enabledModels: ["gemini-3.8-live"], defaultModel: "gemini-3.8-live" },
    };
    const chat = createChatController({ chatProvider: "Google", chatModel: "gemini-3.8-live" });
    const onOpenPal = vi.fn();
    function Composer() {
      const voiceChat = useVoiceChat({
        providerOptions, providerModelCatalog, preferredProvider: "Google", preferredModel: "gemini-3.8-live",
        formatErrorMessage: (error) => String(error),
      });
      return <ChatInputBar chat={chat} voiceChat={voiceChat} onOpenPal={onOpenPal} />;
    }
    render(<Composer />);
    fireEvent.click(screen.getByTitle("通话设置"));
    fireEvent.click(screen.getByText("Agent Platform"));
    fireEvent.click(screen.getByText("Gemini 3.8 Live · Avatar"));
    expect(screen.getByLabelText("音色")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("音色"), { target: { value: "Kore" } });
    fireEvent.change(screen.getByLabelText("口音"), { target: { value: "en-GB" } });
    fireEvent.click(screen.getByText("完成"));
    expect(screen.getByTitle("通话设置")).toHaveTextContent("Gemini 3.8 Live · Avatar · Ben");
    expect(screen.getByTitle("通话设置")).toHaveTextContent("Kore");
    expect(document.querySelector(".vsLiveAvatarPlayer")).toBeNull();
    expect(chat.onModelChoiceChange).toHaveBeenCalledWith("AgentPlatform\u001fgemini-3.8-live");
    expect(onOpenPal).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTitle("通话设置"));
    expect(screen.getByLabelText("口音")).toHaveValue("en-GB");
    fireEvent.click(screen.getByText("改为语音通话"));
    expect(document.querySelector(".vsLiveAvatarPlayer")).toBeNull();
    expect(screen.getByTitle("通话设置")).not.toHaveTextContent("Avatar");
  });
  it("starts Gemini Avatar in Chat without opening the Tavus face page", () => {
    const voiceChat = createVoiceChatController({
      voiceChatProvider: "AgentPlatform", voiceChatModel: "gemini-3.8-live",
      voiceChatAvatarSupported: true, voiceChatLiveAvatar: true,
    });
    const onOpenPal = vi.fn();
    render(<ChatInputBar chat={createChatController({ chatProvider: "AgentPlatform", chatModel: "gemini-3.8-live" })} voiceChat={voiceChat} onOpenPal={onOpenPal} />);
    fireEvent.click(screen.getByTitle("通话设置"));
    fireEvent.change(screen.getByLabelText("形象"), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("预置分身名称"), { target: { value: "FaceFromCloud" } });
    expect(voiceChat.onAvatarNameChange).toHaveBeenCalledWith("FaceFromCloud");
    fireEvent.click(screen.getByText("完成"));
    fireEvent.click(screen.getByLabelText("实时通话"));
    expect(voiceChat.onToggleRecording).toHaveBeenCalledOnce();
    expect(onOpenPal).not.toHaveBeenCalled();
  });
  it("keeps the avatar out of the composer and preserves its labels after hang-up", () => {
    const voiceChat = createVoiceChatController({
      voiceChatProvider: "AgentPlatform", voiceChatModel: "gemini-3.8-live", voiceChatLiveAvatar: true,
      voiceChatRecording: true, voiceChatConnected: true, voiceChatAvatarName: "Leo",
      voiceChatVoice: "Kore", voiceChatVoiceLabel: "Kore",
    });
    const chat = createChatController();
    const { rerender } = render(<ChatInputBar voiceChat={voiceChat} chat={chat} />);
    expect(document.querySelector(".vsLiveAvatarPlayer")).toBeNull();
    expect(document.querySelector(".vsVoiceReadOnlyChip")).toHaveTextContent("Gemini 3.8 Live · Avatar · Leo · Kore");
    rerender(<ChatInputBar voiceChat={{ ...voiceChat, voiceChatRecording: false, voiceChatConnected: false }} chat={chat} />);
    expect(document.querySelector(".vsLiveAvatarPlayer")).toBeNull();
    expect(screen.getByTitle("通话设置")).toHaveTextContent("Gemini 3.8 Live · Avatar · Leo · Kore");
  });
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders textarea with standard placeholder and toolbar buttons", () => {
    const chat = createChatController({
      chatProvider: "Google",
      chatModel: "gemini-3.5-flash",
      chatInput: "",
    });
    const voiceChat = createVoiceChatController();

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    const textarea = screen.getByPlaceholderText(/输入聊天内容/);
    expect(textarea).toBeInTheDocument();
    expect(screen.getByLabelText("附件/图片")).toBeInTheDocument();
    expect(screen.getByLabelText("语音转写")).toBeInTheDocument();
    expect(screen.getByLabelText("实时通话")).toBeInTheDocument();
  });

  it("calls onInputChange and onComposerKeyDown when interacting with textarea", () => {
    const chat = createChatController({
      chatProvider: "Google",
      chatModel: "gemini-3.5-flash",
      chatInput: "Hello",
    });
    const voiceChat = createVoiceChatController();

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    const textarea = screen.getByDisplayValue("Hello");
    fireEvent.change(textarea, { target: { value: "Hello world" } });
    expect(chat.onInputChange).toHaveBeenCalledWith("Hello world");

    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    expect(chat.onComposerKeyDown).toHaveBeenCalledTimes(1);
  });

  it("shows and enables the send button when input is non-empty", () => {
    const chat = createChatController({
      chatInput: "Non-empty message",
      chatBusy: false,
    });
    const voiceChat = createVoiceChatController();

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    const sendBtn = screen.getByLabelText("发送");
    expect(sendBtn).toBeInTheDocument();
    expect(sendBtn).not.toBeDisabled();
  });

  it("disables send button when chat is busy", () => {
    const chat = createChatController({
      chatInput: "Sending...",
      chatBusy: true,
    });
    const voiceChat = createVoiceChatController();

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    const sendBtn = screen.getByLabelText("发送");
    expect(sendBtn).toBeDisabled();
  });

  it("hides send button when input is empty and there are no attachments", () => {
    const chat = createChatController({
      chatInput: "",
      chatAttachments: [],
    });
    const voiceChat = createVoiceChatController();

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    expect(screen.queryByLabelText("发送")).not.toBeInTheDocument();
  });

  it("shows attachment pills and deletes them when clicking the remove button", () => {
    const chat = createChatController({
      chatInput: "",
      chatAttachments: [
        { name: "document.pdf", content: "PDF content", type: "pdf", size: 1024 },
        { name: "image.png", content: "[Image]", type: "image", dataUrl: "data:image/png;base64,123", size: 2048 },
      ],
    });
    const voiceChat = createVoiceChatController();

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    expect(screen.getByText("document.pdf")).toBeInTheDocument();
    expect(screen.getByText("image.png")).toBeInTheDocument();

    const deleteButtons = screen.getAllByTitle("删除附件");
    expect(deleteButtons).toHaveLength(2);

    fireEvent.click(deleteButtons[0]);
    expect(chat.removeChatAttachment).toHaveBeenCalledWith(0);
  });

  it("renders realtime mode controls when a realtime model is selected", () => {
    const chat = createChatController({
      chatProvider: "Google",
      chatModel: "gemini-3.1-flash-live-preview", // realtime model
      chatInput: "",
    });
    const voiceChat = createVoiceChatController({
      voiceChatSupported: true,
      voiceChatBusy: false,
    });

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    // Dictation mic button is hidden for realtime models
    expect(screen.queryByLabelText("语音转写")).not.toBeInTheDocument();

    // Call button is enabled
    const callBtn = screen.getByLabelText("实时通话");
    expect(callBtn).not.toBeDisabled();

    fireEvent.click(callBtn);
    expect(voiceChat.onToggleRecording).toHaveBeenCalledTimes(1);
  });

  it("handles Tavus video PAL mode when provider is Tavus", () => {
    const onOpenPal = vi.fn();
    const chat = createChatController({
      chatProvider: "Tavus",
      chatModel: "rachel-tavus-v1",
      chatInput: "",
    });
    const voiceChat = createVoiceChatController({
      voiceChatProvider: "Tavus",
      voiceChatSupported: true,
      voiceChatBusy: false,
    });

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} onOpenPal={onOpenPal} />);

    const palBtn = screen.getByLabelText("开启视频分身");
    expect(palBtn).toBeInTheDocument();

    fireEvent.click(palBtn);
    expect(onOpenPal).toHaveBeenCalledTimes(1);
  });

  it("opens the real Video PAL page from the Tavus model menu", () => {
    const onOpenPal = vi.fn();
    const chat = createChatController();
    const voiceChat = createVoiceChatController({
      voiceChatRealtimeChoicesByProvider: [
        { provider: "Tavus", models: ["tavus-video-pal", "tavus-phoenix-2"] },
      ],
    });
    render(<ChatInputBar chat={chat} voiceChat={voiceChat} onOpenPal={onOpenPal} />);
    fireEvent.click(screen.getByTitle("通话设置"));
    fireEvent.mouseEnter(screen.getByText("Tavus"));
    fireEvent.click(screen.getByText("打开视频分身"));
    expect(onOpenPal).toHaveBeenCalledTimes(1);
    expect(voiceChat.onToggleRecording).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "通话设置" })).not.toBeInTheDocument();
  });

  it("displays live voice call banner and handles hang up when voice session is active", () => {
    const chat = createChatController({
      chatProvider: "DashScope",
      chatModel: "qwen3.5-omni-plus-realtime",
    });
    const voiceChat = createVoiceChatController({
      voiceChatRecording: true,
      voiceChatConnected: true,
      voiceChatProvider: "DashScope",
      voiceChatModel: "qwen3.5-omni-plus-realtime",
      voiceChatVoiceLabel: "知晓 (女)",
    });

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    expect(screen.getByText(/已连接/)).toBeInTheDocument();
    expect(screen.getByTitle("挂断实时通话")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("挂断实时通话"));
    expect(voiceChat.onToggleRecording).toHaveBeenCalledTimes(1);
  });

  it("handles mute/unmute and displays formatted call duration during active voice call", () => {
    const onToggleMute = vi.fn();
    const chat = createChatController();
    const voiceChat = createVoiceChatController({
      voiceChatRecording: true,
      voiceChatConnected: true,
      voiceChatMuted: false,
      voiceChatDuration: 125, // 02:05
      onToggleMute,
    });

    const { rerender } = render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    // Shows timer 02:05
    expect(screen.getByText("02:05")).toBeInTheDocument();

    // Shows Mute button
    const muteBtn = screen.getByLabelText("静音麦克风");
    expect(muteBtn).toBeInTheDocument();
    fireEvent.click(muteBtn);
    expect(onToggleMute).toHaveBeenCalledTimes(1);

    // Rerender as muted
    const mutedVoiceChat = createVoiceChatController({
      ...voiceChat,
      voiceChatMuted: true,
      onToggleMute,
    });
    rerender(<ChatInputBar chat={chat} voiceChat={mutedVoiceChat} />);

    expect(screen.getByLabelText("取消静音")).toBeInTheDocument();
    expect(screen.getAllByText("已静音").length).toBeGreaterThanOrEqual(1);
  });

  it("shows dictation unsupported error hint when browser SpeechRecognition is absent", () => {
    const chat = createChatController({
      chatProvider: "Google",
      chatModel: "gemini-3.5-flash", // non-realtime
    });
    const voiceChat = createVoiceChatController();

    // Ensure SpeechRecognition is undefined on window
    delete (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;

    render(<ChatInputBar chat={chat} voiceChat={voiceChat} />);

    const micBtn = screen.getByLabelText("语音转写");
    fireEvent.click(micBtn);

    expect(screen.getByText(/不支持语音转文字/)).toBeInTheDocument();
  });
});
