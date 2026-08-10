/**
 * Text-file export that works in both browser and pywebview desktop mode.
 *
 * In desktop mode, blob-anchor downloads (`<a download>`) are silently
 * swallowed by the embedded WebView, so exports must go through the native
 * save dialog exposed by the `save_text_file` JS bridge (run_web_desktop.py).
 * In a plain browser the bridge is absent and we fall back to the anchor
 * download.
 */

export type DesktopSaveResult = {
  ok?: boolean;
  cancelled?: boolean;
  message?: string;
  path?: string;
};

type DesktopSavePayload = {
  filename: string;
  data_base64: string;
};

type DesktopBridgeWindow = Window & {
  pywebview?: {
    api?: {
      save_text_file?: (payload: DesktopSavePayload) => Promise<DesktopSaveResult>;
      save_audio_file?: (payload: DesktopSavePayload) => Promise<DesktopSaveResult>;
    };
  };
};

export type TextExportOutcome =
  | { kind: "saved-desktop"; path?: string }
  | { kind: "downloaded-browser" }
  | { kind: "cancelled" }
  | { kind: "failed"; message: string };

/** Chunked so the spread in `fromCharCode` cannot blow the argument limit on
 * multi-megabyte media. */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

/** UTF-8-safe base64 (btoa alone chokes on non-Latin1 text). */
export function textToBase64(text: string): string {
  return bytesToBase64(new TextEncoder().encode(text));
}

/**
 * Download a binary asset served by our own backend (e.g. a job's source audio).
 *
 * A plain `<a download href="http://127.0.0.1:8000/...">` does not work here for
 * two independent reasons, which is why this goes through fetch + blob:
 *  - `download` is ignored for cross-origin URLs, and in dev the SPA runs on
 *    :5173 while the API is on :8000 — the browser navigates to the audio
 *    instead of saving it, tearing down the SPA.
 *  - pywebview swallows anchor downloads entirely, so desktop mode needs the
 *    native save dialog bridge.
 * `init` is forwarded to fetch for callers that do need credentials/headers.
 */
export async function downloadBinaryFile(
  url: string,
  filename: string,
  init?: RequestInit
): Promise<TextExportOutcome> {
  let blob: Blob;
  try {
    const response = await fetch(url, init);
    if (!response.ok) {
      return { kind: "failed", message: `HTTP ${response.status}` };
    }
    blob = await response.blob();
  } catch (err) {
    return {
      kind: "failed",
      message: err instanceof Error ? err.message : String(err),
    };
  }

  const desktopSave = (window as DesktopBridgeWindow).pywebview?.api?.save_audio_file;
  if (desktopSave) {
    try {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const result = await desktopSave({
        filename,
        data_base64: bytesToBase64(bytes),
      });
      if (result?.ok) return { kind: "saved-desktop", path: result.path };
      if (result?.cancelled) return { kind: "cancelled" };
      return { kind: "failed", message: result?.message || "Desktop save failed." };
    } catch (err) {
      return {
        kind: "failed",
        message: err instanceof Error ? err.message : String(err),
      };
    }
  }

  try {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoking synchronously can cancel the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
    return { kind: "downloaded-browser" };
  } catch (err) {
    return {
      kind: "failed",
      message: err instanceof Error ? err.message : String(err),
    };
  }
}

export async function exportTextFile(
  filename: string,
  content: string,
  mimeType = "text/plain"
): Promise<TextExportOutcome> {
  const desktopSave = (window as DesktopBridgeWindow).pywebview?.api?.save_text_file;
  if (desktopSave) {
    try {
      const result = await desktopSave({
        filename,
        data_base64: textToBase64(content),
      });
      if (result?.ok) return { kind: "saved-desktop", path: result.path };
      if (result?.cancelled) return { kind: "cancelled" };
      return {
        kind: "failed",
        message: result?.message || "Desktop export failed.",
      };
    } catch (err) {
      return {
        kind: "failed",
        message: err instanceof Error ? err.message : String(err),
      };
    }
  }

  try {
    const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return { kind: "downloaded-browser" };
  } catch (err) {
    return {
      kind: "failed",
      message: err instanceof Error ? err.message : String(err),
    };
  }
}
