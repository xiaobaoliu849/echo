import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WordTimestamp } from "../../api";
import TranscriptionSubtitlePlayer from "./TranscriptionSubtitlePlayer";

const WORDS: WordTimestamp[] = [
  { text: "第一句字幕。", start: 0, end: 2 },
  { text: "第二句提到苹果。", start: 2, end: 4 },
  { text: "第三句也提到苹果。", start: 4, end: 6 },
  { text: "第四句没有关键词。", start: 6, end: 8 },
];

const TRANSCRIPT = WORDS.map((w) => w.text).join("");

function renderPlayer(overrides: Partial<React.ComponentProps<typeof TranscriptionSubtitlePlayer>> = {}) {
  return render(
    <TranscriptionSubtitlePlayer
      transcript={TRANSCRIPT}
      words={WORDS}
      audioSourceUrl="http://127.0.0.1:8000/api/transcription/jobs/tx_1/audio"
      audioDuration={8}
      fileName="会议录音.m4a"
      onAudioDurationChange={() => {}}
      {...overrides}
    />
  );
}

describe("TranscriptionSubtitlePlayer", () => {
  beforeEach(() => {
    // jsdom does not implement media playback.
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).pywebview;
  });

  function openSearch() {
    fireEvent.click(screen.getByRole("button", { name: "搜索字幕" }));
    return screen.getByPlaceholderText("搜索字幕…");
  }

  it("keeps the search input usable and reports the match count", () => {
    renderPlayer();
    const input = openSearch();

    // The input lives on its own row, not squeezed between the tool buttons.
    expect(input.closest(".vsSubtitleSearchRow")).not.toBeNull();
    expect(input.closest(".vsSubtitleToolbar")).toBeNull();

    fireEvent.change(input, { target: { value: "苹果" } });
    expect(screen.getByText("1/2")).toBeInTheDocument();

    // Typing keeps focus in the input rather than being stolen by a scroll.
    expect(document.activeElement).toBe(input);
  });

  it("cycles matches with the nav buttons and wraps around", () => {
    renderPlayer();
    const input = openSearch();
    fireEvent.change(input, { target: { value: "苹果" } });

    fireEvent.click(screen.getByRole("button", { name: "下一个匹配" }));
    expect(screen.getByText("2/2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一个匹配" }));
    expect(screen.getByText("1/2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "上一个匹配" }));
    expect(screen.getByText("2/2")).toBeInTheDocument();
  });

  it("advances matches on Enter and closes on Escape", () => {
    renderPlayer();
    const input = openSearch();
    fireEvent.change(input, { target: { value: "苹果" } });

    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("2/2")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByPlaceholderText("搜索字幕…")).not.toBeInTheDocument();
  });

  it("reports no results instead of a bare 0/0 and disables the nav buttons", () => {
    renderPlayer();
    const input = openSearch();
    fireEvent.change(input, { target: { value: "不存在的词" } });

    expect(screen.getByText("无结果")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一个匹配" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一个匹配" })).toBeDisabled();
  });

  function mockFetchResponse(body: Blob, status = 200) {
    // jsdom's Response has no .blob(); hand it one that resolves.
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      blob: () => Promise.resolve(body),
    } as unknown as Response);
  }

  it("downloads the source file via fetch + blob rather than navigating", async () => {
    const blob = new Blob(["audio-bytes"], { type: "audio/mp4" });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    mockFetchResponse(blob);
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    (URL as any).createObjectURL = createObjectURL;
    (URL as any).revokeObjectURL = revokeObjectURL;

    const clicked: HTMLAnchorElement[] = [];
    const realClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      clicked.push(this);
    };

    try {
      renderPlayer();
      fireEvent.click(screen.getByRole("button", { name: "下载源文件" }));

      await waitFor(() => expect(clicked).toHaveLength(1));

      // ?download=1 makes the backend send Content-Disposition: attachment.
      expect(fetchMock).toHaveBeenCalledWith(
        "http://127.0.0.1:8000/api/transcription/jobs/tx_1/audio?download=1",
        undefined
      );
      // The saved file keeps the job's own name, not the job id.
      expect(clicked[0].download).toBe("会议录音.m4a");
      expect(clicked[0].href).toBe("blob:mock");
      expect(createObjectURL).toHaveBeenCalled();
    } finally {
      HTMLAnchorElement.prototype.click = realClick;
    }
  });

  it("routes the download through the desktop bridge in pywebview mode", async () => {
    const saveAudio = vi.fn().mockResolvedValue({ ok: true, path: "C:/tmp/会议录音.m4a" });
    (window as any).pywebview = { api: { save_audio_file: saveAudio } };
    mockFetchResponse(new Blob(["audio-bytes"]));

    renderPlayer();
    fireEvent.click(screen.getByRole("button", { name: "下载源文件" }));

    await waitFor(() => expect(saveAudio).toHaveBeenCalledTimes(1));
    expect(saveAudio.mock.calls[0][0].filename).toBe("会议录音.m4a");
    expect(saveAudio.mock.calls[0][0].data_base64).toBeTruthy();
  });

  it("surfaces a download failure instead of failing silently", async () => {
    mockFetchResponse(new Blob(["nope"]), 404);

    renderPlayer();
    fireEvent.click(screen.getByRole("button", { name: "下载源文件" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/下载失败/)).toBeInTheDocument();
  });

  it("recovers the player when a new job is opened after a media error", () => {
    const { rerender } = renderPlayer();

    // A job whose audio 404s hides the transport…
    fireEvent.error(screen.getByLabelText("转写音频播放器"));
    expect(screen.queryByRole("button", { name: "播放" })).not.toBeInTheDocument();
    // …and says why, rather than silently collapsing to a transcript column.
    expect(screen.getByRole("alert")).toHaveTextContent(/源音频无法播放/);

    // Opening the next job must bring the player back.
    rerender(
      <TranscriptionSubtitlePlayer
        transcript={TRANSCRIPT}
        words={WORDS}
        audioSourceUrl="http://127.0.0.1:8000/api/transcription/jobs/tx_2/audio"
        audioDuration={8}
        fileName="第二个录音.m4a"
        onAudioDurationChange={() => {}}
      />
    );
    expect(screen.getByRole("button", { name: "播放" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps cue rows clickable after switching jobs", () => {
    const { rerender } = renderPlayer();

    rerender(
      <TranscriptionSubtitlePlayer
        transcript={TRANSCRIPT}
        words={WORDS}
        audioSourceUrl="http://127.0.0.1:8000/api/transcription/jobs/tx_2/audio"
        audioDuration={8}
        fileName="第二个录音.m4a"
        onAudioDurationChange={() => {}}
      />
    );

    // Search still finds and reveals rows — proves the row refs survived the
    // swap (a reset that wiped rowEls would leave them null).
    const input = openSearch();
    fireEvent.change(input, { target: { value: "苹果" } });
    expect(screen.getByText("1/2")).toBeInTheDocument();

    // Highlighting splits the text node, so match on the row's textContent.
    const row = screen
      .getAllByRole("button")
      .find((el) => el.textContent?.includes("第二句提到苹果。"));
    expect(row).toBeDefined();
    fireEvent.click(row!);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it("falls back to a transcript-only column when there is no media", () => {
    renderPlayer({ audioSourceUrl: undefined });

    expect(screen.queryByRole("button", { name: "播放" })).not.toBeInTheDocument();
    // Search still works without media.
    const input = openSearch();
    fireEvent.change(input, { target: { value: "苹果" } });
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });
});
