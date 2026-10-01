export type AvatarFrame = { mimeType: string; data: string };

/** Ordered MP4 fragments need one MediaSource, not a new data URL per packet. */
export class LiveAvatarPlayback {
  private media: MediaSource | null = null;
  private buffer: SourceBuffer | null = null;
  private url = "";
  private pending: Uint8Array<ArrayBuffer>[] = [];
  private pendingBytes = 0;
  private mime = "";
  private initialization: Uint8Array<ArrayBuffer> | null = null;

  constructor(private video: HTMLVideoElement, private report: (error: boolean) => void) {}

  reset(preserveInitialization = false) {
    this.pending = [];
    this.pendingBytes = 0;
    this.buffer = null;
    const media = this.media;
    this.media = null;
    if (media?.readyState === "open") {
      try { media.endOfStream(); } catch { /* An append may still be finishing. */ }
    }
    this.video.removeAttribute("src");
    this.video.load();
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = "";
    this.mime = "";
    if (!preserveInitialization) this.initialization = null;
  }

  append(frame: AvatarFrame) {
    try {
      if (!frame.mimeType.startsWith("video/")) return;
      const binary = atob(frame.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      if (!bytes.length) return;
      const init = this.readInitialization(bytes);
      if (init) this.initialization = init;
      if (!this.media) {
        if (typeof MediaSource === "undefined") throw new Error("MediaSource unavailable");
        let mime = frame.mimeType;
        // Google documents MP4 output; use the AVC profile from its init segment.
        if (mime === "video/mp4") {
          const header = this.initialization || bytes;
          for (let i = 0; i + 7 < header.length; i++) {
            if (header[i] === 0x61 && header[i + 1] === 0x76 && header[i + 2] === 0x63 && header[i + 3] === 0x43) {
              const codec = Array.from(header.slice(i + 5, i + 8)).map((v) => v.toString(16).padStart(2, "0")).join("");
              // Live Avatar MP4 muxes synthesized speech (AAC) with H.264.
              const hasAac = new TextDecoder("latin1").decode(header).includes("mp4a");
              mime = `video/mp4; codecs="avc1.${codec}${hasAac ? ", mp4a.40.2" : ""}"`;
              break;
            }
          }
        }
        if (!MediaSource.isTypeSupported(mime)) throw new Error("Unsupported avatar codec");
        this.mime = mime;
        const media = new MediaSource();
        this.media = media;
        this.url = URL.createObjectURL(media);
        this.video.src = this.url;
        // Google sends ftyp/moov once per session. A new MediaSource after
        // barge-in needs that init before the continuing moof/mdat packets.
        if (!init && this.initialization) {
          this.pending.push(this.initialization);
          this.pendingBytes += this.initialization.length;
        }
        media.addEventListener("sourceopen", () => {
          if (this.media !== media) return;
          try {
            this.buffer = media.addSourceBuffer(this.mime);
            this.buffer.mode = "sequence";
            this.buffer.addEventListener("updateend", () => { if (this.media === media) this.flush(); });
            this.buffer.addEventListener("error", () => { if (this.media === media) this.fail(); });
            this.flush();
          } catch { this.fail(); }
        }, { once: true });
      }
      this.pending.push(bytes);
      this.pendingBytes += bytes.length;
      if (this.pendingBytes > 16 * 1024 * 1024) throw new Error("Avatar playback queue overflow");
      this.flush();
    } catch { this.fail(); }
  }

  private readInitialization(bytes: Uint8Array<ArrayBuffer>): Uint8Array<ArrayBuffer> | null {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let offset = 0;
    let hasFtyp = false;
    while (offset + 8 <= bytes.length) {
      const size = view.getUint32(offset);
      if (size < 8 || offset + size > bytes.length) return null;
      const tag = String.fromCharCode(...bytes.slice(offset + 4, offset + 8));
      if (tag === "ftyp") hasFtyp = true;
      if (tag === "moov" && hasFtyp) return bytes.slice(0, offset + size);
      offset += size;
    }
    return null;
  }

  private flush() {
    const buffer = this.buffer;
    if (!buffer || buffer.updating || this.media?.readyState !== "open") return;
    try {
      // Keep a bounded playback window for long conversations.
      if (buffer.buffered.length && this.video.currentTime > 15 && buffer.buffered.start(0) < this.video.currentTime - 10) {
        buffer.remove(0, this.video.currentTime - 10);
        return;
      }
      const bytes = this.pending.shift();
      if (!bytes) return;
      this.pendingBytes -= bytes.length;
      buffer.appendBuffer(bytes);
      this.report(false);
      void this.video.play().catch(() => this.report(true));
    } catch { this.fail(); }
  }

  private fail() { this.reset(true); this.report(true); }
}
