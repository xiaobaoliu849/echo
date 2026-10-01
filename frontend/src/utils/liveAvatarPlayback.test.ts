import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveAvatarPlayback } from "./liveAvatarPlayback";

class FakeBuffer extends EventTarget {
  updating = false;
  mode = "";
  buffered = { length: 0, start: () => 0 };
  appendBuffer = vi.fn((_bytes: Uint8Array) => { this.updating = true; });
  remove = vi.fn();
  finish() { this.updating = false; this.dispatchEvent(new Event("updateend")); }
}
class FakeMedia extends EventTarget {
  static instances: FakeMedia[] = [];
  static isTypeSupported = vi.fn(() => true);
  readyState = "closed";
  buffer = new FakeBuffer();
  addSourceBuffer = vi.fn(() => this.buffer);
  endOfStream = vi.fn();
  constructor() { super(); FakeMedia.instances.push(this); }
  open() { this.readyState = "open"; this.dispatchEvent(new Event("sourceopen")); }
}

describe("LiveAvatarPlayback", () => {
  beforeEach(() => {
    FakeMedia.instances = [];
    vi.stubGlobal("MediaSource", FakeMedia);
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:avatar"), revokeObjectURL: vi.fn() });
  });
  afterEach(() => { vi.unstubAllGlobals(); });
  function setup() {
    const video = { src: "", currentTime: 0, play: vi.fn(async () => {}), load: vi.fn(), removeAttribute: vi.fn() };
    const report = vi.fn();
    return { video, report, player: new LiveAvatarPlayback(video as unknown as HTMLVideoElement, report) };
  }
  it("preserves fragments received before sourceopen and while appendBuffer is busy", () => {
    const { player } = setup();
    player.append({ mimeType: "video/mp4", data: btoa("init") });
    player.append({ mimeType: "video/mp4", data: btoa("second") });
    const media = FakeMedia.instances[0];
    expect(media.buffer.appendBuffer).not.toHaveBeenCalled();
    media.open();
    expect(media.buffer.appendBuffer).toHaveBeenCalledTimes(1);
    media.buffer.finish();
    expect(media.buffer.appendBuffer).toHaveBeenCalledTimes(2);
    expect(Array.from(media.buffer.appendBuffer.mock.calls[1][0] as Uint8Array)).toEqual(Array.from(new TextEncoder().encode("second")));
  });
  it("declares both actual Google H.264 and AAC codecs", () => {
    const { player, video } = setup();
    player.append({ mimeType: "video/mp4", data: btoa("avcC" + String.fromCharCode(1, 0x42, 0xc0, 0x1f) + "mp4a") });
    const media = FakeMedia.instances[0];
    media.open();
    expect(media.addSourceBuffer).toHaveBeenCalledWith('video/mp4; codecs="avc1.42c01f, mp4a.40.2"');
    expect(video.play).toHaveBeenCalled();
  });
  it("discards queued fragments and stale callbacks when interrupted or unmounted", () => {
    const { player, video } = setup();
    player.append({ mimeType: "video/mp4", data: btoa("stale") });
    const media = FakeMedia.instances[0];
    player.reset();
    media.open();
    expect(media.addSourceBuffer).not.toHaveBeenCalled();
    expect(video.removeAttribute).toHaveBeenCalledWith("src");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:avatar");
  });
  it("reuses the session init after interruption when later replies contain only fragments", () => {
    function box(tag: string, payload = "") {
      const bytes = new Uint8Array(8 + payload.length);
      new DataView(bytes.buffer).setUint32(0, bytes.length);
      bytes.set(new TextEncoder().encode(tag + payload), 4);
      return bytes;
    }
    const init = new Uint8Array([...box("ftyp"), ...box("moov", "avcC" + String.fromCharCode(1, 0x42, 0x40, 0x1f) + "mp4a")]);
    const { player } = setup();
    player.append({ mimeType: "video/mp4", data: btoa(String.fromCharCode(...init)) });
    FakeMedia.instances[0].open();
    player.reset(true);
    player.append({ mimeType: "video/mp4", data: btoa("next-fragment") });
    const media = FakeMedia.instances[1];
    media.open();
    expect(media.buffer.appendBuffer.mock.calls[0][0]).toEqual(init);
    media.buffer.finish();
    expect(Array.from(media.buffer.appendBuffer.mock.calls[1][0])).toEqual(Array.from(new TextEncoder().encode("next-fragment")));
    player.reset();
  });
});
