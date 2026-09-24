import { act, renderHook } from "@testing-library/react";
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

  it("does not auto-fetch custom voices before DashScope API key is configured", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    renderHook(() =>
      useVoiceManagement({ formatErrorMessage, dashscopeApiKeyConfigured: false })
    );

    expect(listCustomVoices).not.toHaveBeenCalled();
  });

  it("auto-fetches custom voices when DashScope API key is configured", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    renderHook(() =>
      useVoiceManagement({ formatErrorMessage, dashscopeApiKeyConfigured: true })
    );

    expect(listCustomVoices).toHaveBeenCalledWith("voice_design", "qwen");
    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "qwen");
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

    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "elevenlabs");
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

    expect(listCustomVoices).toHaveBeenCalledWith("voice_design", "gemini");
    expect(listCustomVoices).toHaveBeenCalledWith("voice_clone", "gemini");
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
});
