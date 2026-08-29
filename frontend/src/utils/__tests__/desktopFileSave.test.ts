import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  downloadBinaryFile,
  exportTextFile,
  textToBase64,
} from "../desktopFileSave";

type CustomPywebviewWindow = Window & {
  pywebview?: {
    api?: {
      save_text_file?: ReturnType<typeof vi.fn>;
      save_audio_file?: ReturnType<typeof vi.fn>;
    };
  };
};

describe("desktopFileSave", () => {
  const win = window as CustomPywebviewWindow;

  beforeEach(() => {
    delete win.pywebview;
    vi.restoreAllMocks();
  });

  afterEach(() => {
    delete win.pywebview;
  });

  describe("textToBase64", () => {
    it("encodes standard ASCII strings correctly", () => {
      const input = "Hello, world!";
      const b64 = textToBase64(input);
      expect(atob(b64)).toBe(input);
    });

    it("encodes UTF-8 multi-byte characters and CJK without throw", () => {
      const input = "你好，世界！🌟 Special chars: é, à, ü, 🚀";
      const b64 = textToBase64(input);
      expect(typeof b64).toBe("string");
      expect(b64.length).toBeGreaterThan(0);

      // Verify decoding via TextDecoder
      const decodedBytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const decodedText = new TextDecoder().decode(decodedBytes);
      expect(decodedText).toBe(input);
    });
  });

  describe("exportTextFile in Desktop mode (pywebview present)", () => {
    it("returns saved-desktop when bridge save_text_file succeeds", async () => {
      const mockSave = vi.fn().mockResolvedValue({ ok: true, path: "C:\\Users\\Test\\file.txt" });
      win.pywebview = {
        api: {
          save_text_file: mockSave,
        },
      };

      const result = await exportTextFile("file.txt", "Hello content", "text/plain");

      expect(mockSave).toHaveBeenCalledTimes(1);
      expect(mockSave).toHaveBeenCalledWith({
        filename: "file.txt",
        data_base64: textToBase64("Hello content"),
      });
      expect(result).toEqual({ kind: "saved-desktop", path: "C:\\Users\\Test\\file.txt" });
    });

    it("returns cancelled when user cancels file picker", async () => {
      const mockSave = vi.fn().mockResolvedValue({ cancelled: true });
      win.pywebview = {
        api: {
          save_text_file: mockSave,
        },
      };

      const result = await exportTextFile("file.txt", "Hello content");
      expect(result).toEqual({ kind: "cancelled" });
    });

    it("returns failed when bridge reports failure", async () => {
      const mockSave = vi.fn().mockResolvedValue({ ok: false, message: "Permission denied" });
      win.pywebview = {
        api: {
          save_text_file: mockSave,
        },
      };

      const result = await exportTextFile("file.txt", "Hello content");
      expect(result).toEqual({ kind: "failed", message: "Permission denied" });
    });

    it("returns failed when bridge throws an exception", async () => {
      const mockSave = vi.fn().mockRejectedValue(new Error("Bridge crashed"));
      win.pywebview = {
        api: {
          save_text_file: mockSave,
        },
      };

      const result = await exportTextFile("file.txt", "Hello content");
      expect(result).toEqual({ kind: "failed", message: "Bridge crashed" });
    });
  });

  describe("exportTextFile in Browser mode (fallback)", () => {
    it("creates blob download link and triggers click", async () => {
      const createObjectURLMock = vi.fn().mockReturnValue("blob:http://localhost/123");
      const revokeObjectURLMock = vi.fn();
      globalThis.URL.createObjectURL = createObjectURLMock;
      globalThis.URL.revokeObjectURL = revokeObjectURLMock;

      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      const result = await exportTextFile("export.srt", "1\n00:00:00 --> 00:00:01\nHi");

      expect(createObjectURLMock).toHaveBeenCalledTimes(1);
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
      expect(result).toEqual({ kind: "downloaded-browser" });
    });

    it("handles failure when DOM creation or URL method throws", async () => {
      globalThis.URL.createObjectURL = vi.fn().mockImplementation(() => {
        throw new Error("Blob creation failed");
      });

      const result = await exportTextFile("export.txt", "content");
      expect(result).toEqual({ kind: "failed", message: "Blob creation failed" });
    });
  });

  describe("downloadBinaryFile in Desktop mode", () => {
    it("fetches blob, converts to base64, and calls save_audio_file", async () => {
      const fakeBytes = new Uint8Array([1, 2, 3, 4, 5]);
      const mockBlob = new Blob([fakeBytes], { type: "audio/mpeg" });
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(mockBlob),
      } as unknown as Response);

      const mockSaveAudio = vi.fn().mockResolvedValue({ ok: true, path: "C:\\audio.mp3" });
      win.pywebview = {
        api: {
          save_audio_file: mockSaveAudio,
        },
      };

      const result = await downloadBinaryFile("http://127.0.0.1:8000/audio.mp3", "audio.mp3");

      expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/audio.mp3", undefined);
      expect(mockSaveAudio).toHaveBeenCalledTimes(1);
      expect(result).toEqual({ kind: "saved-desktop", path: "C:\\audio.mp3" });
    });

    it("handles cancellation in desktop mode", async () => {
      const mockBlob = new Blob([new Uint8Array([10, 20])]);
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(mockBlob),
      } as unknown as Response);

      const mockSaveAudio = vi.fn().mockResolvedValue({ cancelled: true });
      win.pywebview = {
        api: {
          save_audio_file: mockSaveAudio,
        },
      };

      const result = await downloadBinaryFile("http://127.0.0.1:8000/audio.mp3", "audio.mp3");
      expect(result).toEqual({ kind: "cancelled" });
    });
  });

  describe("downloadBinaryFile in Browser mode", () => {
    it("downloads blob via anchor element click in browser mode", async () => {
      const mockBlob = new Blob([new Uint8Array([1, 2, 3])]);
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(mockBlob),
      } as unknown as Response);

      const createObjectURLMock = vi.fn().mockReturnValue("blob:http://localhost/audio-blob");
      globalThis.URL.createObjectURL = createObjectURLMock;
      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      const result = await downloadBinaryFile("http://127.0.0.1:8000/audio.mp3", "audio.mp3");

      expect(createObjectURLMock).toHaveBeenCalledWith(mockBlob);
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(result).toEqual({ kind: "downloaded-browser" });
    });

    it("returns failed when HTTP response is not ok", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
      } as unknown as Response);

      const result = await downloadBinaryFile("http://127.0.0.1:8000/missing.mp3", "missing.mp3");
      expect(result).toEqual({ kind: "failed", message: "HTTP 404" });
    });

    it("returns failed on network fetch error", async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error("Network connection lost"));

      const result = await downloadBinaryFile("http://127.0.0.1:8000/audio.mp3", "audio.mp3");
      expect(result).toEqual({ kind: "failed", message: "Network connection lost" });
    });
  });
});
