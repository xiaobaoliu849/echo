import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChatInputBar from "../chat/ChatInputBar";
import { createChatController, createVoiceChatController } from "../../test/factories";

describe("ChatInputBar", () => {
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
