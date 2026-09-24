import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import useVoiceManagement from "./useVoiceManagement";
import { createFormatErrorMessageStub } from "../test/factories";
import {
  createVoiceClone,
  createVoiceDesign,
  deleteCustomVoice,
  listCustomVoices
} from "../api";

vi.mock("../api", () => ({
  listCustomVoices: vi.fn().mockResolvedValue({ voices: [] }),
  createVoiceDesign: vi.fn(),
  createVoiceClone: vi.fn(),
  deleteCustomVoice: vi.fn()
}));

describe("useVoiceManagement", () => {
  beforeEach(() => {
    vi.mocked(listCustomVoices).mockClear();
    vi.mocked(createVoiceDesign).mockReset();
    vi.mocked(createVoiceClone).mockReset();
    vi.mocked(deleteCustomVoice).mockReset();
  });

  it("applies a design preset and exposes submit readiness", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({ formatErrorMessage })
    );

    act(() => {
      result.current.design.onNameChange("host-voice");
      result.current.design.onApplyPreset("专业、稳重、适合播客主持。");
      result.current.design.onPreviewTextChange("大家好，欢迎来到今天的节目。");
    });

    expect(result.current.design.designPrompt).toContain("专业");
    expect(result.current.design.designInfo).toBe("已应用音色描述预设。");
    expect(result.current.design.designCanSubmit).toBe(true);
  });

  it("loads local clones without a cloud API key", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    renderHook(() =>
      useVoiceManagement({ formatErrorMessage, dashscopeApiKeyConfigured: false })
    );

    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "gpt_sovits", true);
    expect(listCustomVoices).not.toHaveBeenCalledWith("voice_design", "qwen", true);
  });

  it("auto-fetches custom voices when DashScope API key is configured", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    renderHook(() =>
      useVoiceManagement({ formatErrorMessage, dashscopeApiKeyConfigured: true })
    );

    expect(listCustomVoices).toHaveBeenCalledWith("voice_design", "qwen", true);
    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "qwen", true);
  });

  it("fetches ElevenLabs clone voices after switching provider", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({
        formatErrorMessage,
        elevenlabsApiKeyConfigured: true,
      })
    );

    act(() => {
      result.current.setVoiceProvider("elevenlabs");
    });

    await act(async () => {});

    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "elevenlabs", true);
    expect(result.current.cloneProvider).toBe("elevenlabs");
  });

  it("validates clone audio file metadata on selection", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({ formatErrorMessage })
    );

    act(() => {
      result.current.clone.onAudioFileChange(
        new File(["audio"], "sample.wav", { type: "audio/wav" })
      );
      result.current.clone.onNameChange("clone-host");
    });

    expect(result.current.clone.cloneFileSummary).toContain("sample.wav");
    expect(result.current.clone.cloneCanSubmit).toBe(true);
  });

  it("rejects unsupported clone file formats", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({ formatErrorMessage })
    );

    act(() => {
      result.current.clone.onAudioFileChange(
        new File(["video"], "clip.mov", { type: "video/quicktime" })
      );
    });

    expect(result.current.clone.cloneError).toContain("暂不支持该音频格式");
    expect(result.current.clone.cloneCanSubmit).toBe(false);
  });

  it("blocks design submit with weak prompt", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({ formatErrorMessage })
    );

    act(() => {
      result.current.design.onNameChange("demo");
      result.current.design.onPromptChange("太短");
      result.current.design.onPreviewTextChange("你好世界");
    });

    await act(async () => {
      await result.current.design.onSubmit({ preventDefault() {} } as any);
    });

    expect(result.current.design.designError).toContain("至少 10 个字");
  });

  it("fetches Gemini custom voices when Google API key is configured and provider selected", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({
        formatErrorMessage,
        googleApiKeyConfigured: true,
      })
    );

    act(() => {
      result.current.setVoiceProvider("gemini");
    });

    await act(async () => {});

    expect(listCustomVoices).toHaveBeenCalledWith("voice_design", "gemini", true);
    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "gemini", true);
  });

  it("blocks Gemini cloning until a separate consent clip is selected", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() =>
      useVoiceManagement({ formatErrorMessage, googleApiKeyConfigured: true })
    );
    const sample = new File(["sample"], "sample.wav", { type: "audio/wav" });
    const consent = new File(["consent"], "consent.wav", { type: "audio/wav" });
    act(() => {
      result.current.setVoiceProvider("gemini");
      result.current.clone.onAudioFileChange(sample);
      result.current.clone.onNameChange("myvoice");
    });
    expect(result.current.clone.cloneCanSubmit).toBe(false);
    await act(async () => {
      await result.current.clone.onSubmit({ preventDefault() {} } as any);
    });
    expect(result.current.clone.cloneError).toContain("单独录制");
    expect(createVoiceClone).not.toHaveBeenCalled();

    act(() => result.current.clone.onConsentFileChange(consent));
    expect(result.current.clone.cloneCanSubmit).toBe(true);
  });

  it("reports the requested display name after Gemini creates a generated voice ID", async () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    vi.mocked(createVoiceClone).mockResolvedValue({
      voice: "voice_xiao_123",
      preferred_name: "xiao",
      type: "voice_clone",
    });
    const { result } = renderHook(() =>
      useVoiceManagement({ formatErrorMessage, googleApiKeyConfigured: true })
    );
    act(() => {
      result.current.setVoiceProvider("gemini");
      result.current.clone.onNameChange("xiao");
      result.current.clone.onAudioFileChange(new File(["sample"], "sample.wav", { type: "audio/wav" }));
      result.current.clone.onConsentFileChange(new File(["consent"], "consent.wav", { type: "audio/wav" }));
    });

    await act(async () => {
      await result.current.clone.onSubmit({ preventDefault() {} } as any);
    });

    expect(result.current.clone.cloneInfo).toContain("xiao");
    expect(result.current.clone.cloneInfo).not.toContain("voice_xiao_123");
  });

  it("shows Gemini and Qwen clones together and deletes through the matching provider", async () => {
    vi.mocked(listCustomVoices).mockImplementation(async (type, provider) => ({
      voice_type: type,
      count: provider === "gpt_sovits" ? 0 : 1,
      voices: provider === "gpt_sovits" ? [] : [{
        voice: provider === "gemini" ? "voice_gemini_clone" : "qwen_clone",
        type: "voice_clone",
        target_model: provider === "gemini" ? "gemini-3.8-flash-tts" : "qwen3-tts-vc-realtime",
        name: provider === "gemini" ? "My voice" : "Qwen voice",
      }],
    }));
    vi.mocked(deleteCustomVoice).mockResolvedValue();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage: createFormatErrorMessageStub(),
      dashscopeApiKeyConfigured: true,
      googleApiKeyConfigured: true,
    }));
    await act(async () => {});
    expect(result.current.clone.cloneVoices).toEqual(expect.arrayContaining([
      expect.objectContaining({ voice: "voice_gemini_clone", provider: "gemini" }),
      expect.objectContaining({ voice: "qwen_clone", provider: "qwen" }),
    ]));
    await act(async () => {
      await result.current.clone.onDeleteVoice("voice_gemini_clone", "gemini");
    });
    expect(deleteCustomVoice).toHaveBeenCalledWith("voice_gemini_clone", "voice_clone", "gemini");
  });

  it("shows Gemini clones while the Qwen catalog is still loading", async () => {
    let finishQwen!: (value: { voice_type: "voice_clone"; count: number; voices: [] }) => void;
    vi.mocked(listCustomVoices).mockImplementation((type, provider) => {
      if (type === "voice_clone" && provider === "qwen") {
        return new Promise(resolve => { finishQwen = resolve; });
      }
      return Promise.resolve({
        voice_type: type,
        count: provider === "gemini" ? 1 : 0,
        voices: provider === "gemini" ? [{
          voice: "voice_gemini_clone", type: "voice_clone", target_model: "gemini-3.8-flash-tts",
        }] : [],
      });
    });
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      dashscopeApiKeyConfigured: true,
      googleApiKeyConfigured: true,
    }));
    await waitFor(() => expect(result.current.clone.cloneVoices).toEqual(expect.arrayContaining([
      expect.objectContaining({ voice: "voice_gemini_clone", provider: "gemini" }),
    ])));
    expect(result.current.clone.cloneListBusy).toBe(true);
    act(() => finishQwen({ voice_type: "voice_clone", count: 0, voices: [] }));
    await waitFor(() => expect(result.current.clone.cloneListBusy).toBe(false));
  });
});
