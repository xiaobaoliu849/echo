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
    vi.mocked(listCustomVoices).mockReset().mockImplementation(async type => ({ voice_type: type, count: 0, voices: [] }));
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

  it("keeps Qwen and Gemini designed voices together across provider changes", async () => {
    vi.mocked(listCustomVoices).mockImplementation(async (type, provider) => ({
      voice_type: type,
      count: type === "voice_design" ? 1 : 0,
      voices: type === "voice_design" ? [{
        voice: provider === "gemini" ? "gemini-design" : "qwen-design",
        type: "voice_design",
        target_model: provider === "gemini" ? "gemini-3.8-flash-tts" : "qwen3-tts-vd-realtime",
      }] : [],
    }));
    vi.mocked(deleteCustomVoice).mockResolvedValue();
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      dashscopeApiKeyConfigured: true,
      googleApiKeyConfigured: true,
    }));

    await waitFor(() => expect(result.current.design.designVoices).toHaveLength(2));
    expect(result.current.design.designVoices).toEqual(expect.arrayContaining([
      expect.objectContaining({ voice: "qwen-design", provider: "qwen" }),
      expect.objectContaining({ voice: "gemini-design", provider: "gemini" }),
    ]));

    act(() => result.current.setVoiceProvider("gemini"));
    expect(result.current.design.designVoices).toHaveLength(2);
    act(() => result.current.setVoiceProvider("qwen"));
    expect(result.current.design.designVoices).toHaveLength(2);
    act(() => result.current.setVoiceProvider("elevenlabs"));
    expect(result.current.design.designVoices).toHaveLength(2);

    await act(async () => {
      await result.current.design.onDeleteVoice("gemini-design", "gemini");
    });
    expect(deleteCustomVoice).toHaveBeenCalledWith("gemini-design", "voice_design", "gemini");
  });

  it("shows available designs while another provider catalog is slow", async () => {
    let finishQwen!: (value: { voice_type: "voice_design"; count: number; voices: [] }) => void;
    vi.mocked(listCustomVoices).mockImplementation((type, provider) => {
      if (type === "voice_design" && provider === "qwen") {
        return new Promise(resolve => { finishQwen = resolve; });
      }
      return Promise.resolve({
        voice_type: type,
        count: type === "voice_design" ? 1 : 0,
        voices: type === "voice_design" ? [{
          voice: "gemini-design", type: "voice_design", target_model: "gemini-3.8-flash-tts",
        }] : [],
      });
    });
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      dashscopeApiKeyConfigured: true,
      googleApiKeyConfigured: true,
    }));

    await waitFor(() => expect(result.current.design.designVoices).toEqual([
      expect.objectContaining({ voice: "gemini-design", provider: "gemini" }),
    ]));
    expect(result.current.design.designListBusy).toBe(true);
    await act(async () => finishQwen({ voice_type: "voice_design", count: 0, voices: [] }));
    expect(result.current.design.designListBusy).toBe(false);
  });

  it("keeps successful designs visible when one provider fails", async () => {
    vi.mocked(listCustomVoices).mockImplementation(async (type, provider) => {
      if (type === "voice_design" && provider === "qwen") throw new Error("catalog unavailable");
      return {
        voice_type: type,
        count: type === "voice_design" ? 1 : 0,
        voices: type === "voice_design" ? [{
          voice: "gemini-design", type: "voice_design", target_model: "gemini-3.8-flash-tts",
        }] : [],
      };
    });
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      dashscopeApiKeyConfigured: true,
      googleApiKeyConfigured: true,
    }));

    await waitFor(() => expect(result.current.design.designListBusy).toBe(false));
    expect(result.current.design.designVoices).toEqual([
      expect.objectContaining({ voice: "gemini-design", provider: "gemini" }),
    ]);
    expect(result.current.design.designError).toContain("qwen:");
  });

  it("ignores a stale design catalog response after a newer refresh", async () => {
    let finishOld!: (value: { voice_type: "voice_design"; count: number; voices: [] }) => void;
    let designCalls = 0;
    vi.mocked(listCustomVoices).mockImplementation((type, provider) => {
      if (type === "voice_design" && provider === "qwen") {
        designCalls += 1;
        if (designCalls === 1) return new Promise(resolve => { finishOld = resolve; });
        return Promise.resolve({
          voice_type: type, count: 1,
          voices: [{ voice: "current-design", type, target_model: "qwen3-tts-vd-realtime" }],
        });
      }
      return Promise.resolve({ voice_type: type, count: 0, voices: [] });
    });
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      dashscopeApiKeyConfigured: true,
    }));

    await act(async () => result.current.design.onRefresh());
    expect(result.current.design.designVoices).toEqual([
      expect.objectContaining({ voice: "current-design", provider: "qwen" }),
    ]);
    await act(async () => finishOld({ voice_type: "voice_design", count: 0, voices: [] }));
    expect(result.current.design.designVoices).toHaveLength(1);
  });

  it("removes a deleted design even when the follow-up catalog refresh fails", async () => {
    let designCalls = 0;
    vi.mocked(listCustomVoices).mockImplementation(async (type, provider) => {
      if (type === "voice_design" && provider === "qwen") {
        designCalls += 1;
        if (designCalls > 1) throw new Error("catalog unavailable");
        return {
          voice_type: type, count: 1,
          voices: [{ voice: "old-design", type, target_model: "qwen3-tts-vd-realtime" }],
        };
      }
      return { voice_type: type, count: 0, voices: [] };
    });
    vi.mocked(deleteCustomVoice).mockResolvedValue();
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      dashscopeApiKeyConfigured: true,
    }));
    await waitFor(() => expect(result.current.design.designVoices).toHaveLength(1));

    await act(async () => result.current.design.onDeleteVoice("old-design", "qwen"));
    expect(result.current.design.designVoices).toEqual([]);
    expect(result.current.design.designError).toContain("qwen:");
  });

  it("explains that Xiaomi design produces a preview without a saved voice", async () => {
    vi.mocked(createVoiceDesign).mockResolvedValue({
      type: "voice_design",
      preview_audio_data: "audio-data",
    });
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({
      formatErrorMessage,
      xiaomiApiKeyConfigured: true,
    }));
    act(() => result.current.setVoiceProvider("xiaomi"));

    await act(async () => {
      await result.current.design.onSubmit({ preventDefault() {} } as any);
    });
    expect(result.current.design.designInfo).toContain("小米不会保存可复用的音色");
    expect(result.current.design.designPreviewAudio).toContain("audio-data");
    expect(result.current.design.designVoices).toEqual([]);
    expect(listCustomVoices).not.toHaveBeenCalledWith("voice_design", "xiaomi", true);
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

  it("keeps the last design-capable provider after selecting a clone-only provider", () => {
    const formatErrorMessage = createFormatErrorMessageStub();
    const { result } = renderHook(() => useVoiceManagement({ formatErrorMessage }));

    act(() => result.current.setVoiceProvider("gemini"));
    act(() => result.current.setVoiceProvider("gpt_sovits"));
    expect(result.current.voiceProvider).toBe("gemini");
    expect(result.current.cloneProvider).toBe("gpt_sovits");

    act(() => result.current.setVoiceProvider("elevenlabs"));
    expect(result.current.voiceProvider).toBe("gemini");
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
