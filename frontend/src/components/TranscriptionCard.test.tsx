import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TranscriptionCard } from "./TranscriptionCard";
import type { HistoryItem } from "../hooks/useTranscriptionHistory";

function makeItem(overrides: Partial<HistoryItem> = {}): HistoryItem {
  return {
    job_id: "tx_card_001",
    file_name: "项目周会.wav",
    status: "completed",
    updated_at: new Date(Date.now() - 3600_000).toISOString(),
    has_transcript: true,
    memory_saved: false,
    mode: "sync",
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("TranscriptionCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the title without the file extension plus meta info", () => {
    render(
      <TranscriptionCard
        item={makeItem({
          duration_seconds: 3725,
          origin: "upload",
          transcript_preview: "大家好，我们开始本周的例会。",
        })}
        onClick={() => {}}
        onDelete={() => {}}
      />
    );

    expect(screen.getByText("项目周会")).toBeInTheDocument();
    expect(screen.getByText("WAV")).toBeInTheDocument();
    expect(screen.getByText("1:02:05")).toBeInTheDocument();
    expect(screen.getByText(/本地文件/)).toBeInTheDocument();
    expect(screen.getByText(/我们开始本周的例会/)).toBeInTheDocument();
  });

  it("falls back to a friendly title for legacy synthetic storage names", () => {
    render(
      <TranscriptionCard
        item={makeItem({ file_name: "upload_efc957af0fe2.wav" })}
        onClick={() => {}}
        onDelete={() => {}}
      />
    );

    expect(screen.getByText(/未命名录音|Untitled recording/)).toBeInTheDocument();
    expect(screen.queryByText(/upload_efc957af/)).not.toBeInTheDocument();
  });

  it("shows the transcript preview for completed records", () => {
    render(
      <TranscriptionCard
        item={makeItem({ transcript_preview: "会议讨论了发布计划。" })}
        onClick={() => {}}
        onDelete={() => {}}
      />
    );

    expect(screen.getByText(/会议讨论了发布计划/)).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });

  it("shows progress for running records and the error for failed ones", () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <TranscriptionCard
        item={makeItem({ status: "running", progress: "第 3/12 段转写中" })}
        onClick={() => {}}
        onDelete={() => {}}
      />
    );

    expect(screen.getByText(/第 3\/12 段转写中/)).toBeInTheDocument();

    rerender(
      <TranscriptionCard
        item={makeItem({ status: "failed", error: "音频解码失败" })}
        onClick={() => {}}
        onDelete={() => {}}
        onRetry={onRetry}
      />
    );

    expect(screen.getByText(/音频解码失败/)).toBeInTheDocument();
    expect(screen.getByText("重试")).toBeInTheDocument();

    fireEvent.click(screen.getByText("重试"));
    expect(onRetry).toHaveBeenCalled();
  });

  it("commits an inline rename through the onRename callback", () => {
    const onRename = vi.fn();
    render(
      <TranscriptionCard
        item={makeItem()}
        onClick={() => {}}
        onDelete={() => {}}
        onRename={onRename}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "重命名" }));

    const input = screen.getByRole("textbox", { name: /重命名转写记录/ });
    fireEvent.change(input, { target: { value: "最终版会议.wav" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onRename).toHaveBeenCalledWith("tx_card_001", "最终版会议.wav");
  });

  it("cancels an inline rename on Escape without calling back", () => {
    const onRename = vi.fn();
    render(
      <TranscriptionCard
        item={makeItem()}
        onClick={() => {}}
        onDelete={() => {}}
        onRename={onRename}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "重命名" }));
    const input = screen.getByRole("textbox", { name: /重命名转写记录/ });
    fireEvent.change(input, { target: { value: "临时名字" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByText("项目周会")).toBeInTheDocument();
  });

  it("shows the realtime origin for realtime-saved records", () => {
    render(
      <TranscriptionCard
        item={makeItem({ file_name: "实时转写", origin: "realtime" })}
        onClick={() => {}}
        onDelete={() => {}}
      />
    );

    expect(screen.getByText(/实时录音/)).toBeInTheDocument();
  });
});
