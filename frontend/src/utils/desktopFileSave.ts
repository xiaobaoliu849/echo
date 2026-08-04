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

type DesktopBridgeWindow = Window & {
  pywebview?: {
    api?: {
      save_text_file?: (payload: {
        filename: string;
        data_base64: string;
      }) => Promise<DesktopSaveResult>;
    };
  };
};

export type TextExportOutcome =
  | { kind: "saved-desktop"; path?: string }
  | { kind: "downloaded-browser" }
  | { kind: "cancelled" }
  | { kind: "failed"; message: string };

/** UTF-8-safe base64 (btoa alone chokes on non-Latin1 text). */
export function textToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
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
