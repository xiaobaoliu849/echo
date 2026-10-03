import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AvatarTranscriptPanel from "../AvatarTranscriptPanel";

const props = { messages: [], userTranscript: "", interim: false, assistantReply: "", avatarName: "Leo" };

describe("AvatarTranscriptPanel", () => {
  it("keeps repeated utterances and complete long text in the transcript", () => {
    const text = "Long reply. ".repeat(100);
    const { container } = render(<AvatarTranscriptPanel {...props}
      messages={[{ role: "user", content: "Hello" }, { role: "user", content: "Hello" }]}
      userTranscript="Question" assistantReply={text} />);
    expect(screen.getAllByText("Hello")).toHaveLength(2);
    expect(container.querySelector('.vsAvatarTranscriptTurn.assistant p')?.textContent).toBe(text);
    expect(screen.getByText("Question")).toBeInTheDocument();
  });

  it("lets a reader stay on older text while new replies stream", () => {
    const { rerender } = render(<AvatarTranscriptPanel {...props} assistantReply="Start" />);
    const pane = screen.getByLabelText("滚动查看通话转写");
    Object.defineProperties(pane, { scrollHeight: { value: 2000 }, clientHeight: { value: 400 } });
    pane.scrollTop = 100;
    fireEvent.scroll(pane);
    rerender(<AvatarTranscriptPanel {...props} assistantReply="Start and continue" />);
    expect(pane.scrollTop).toBe(100);
    pane.scrollTop = 1600;
    fireEvent.scroll(pane);
    rerender(<AvatarTranscriptPanel {...props} assistantReply="Start and continue again" />);
    expect(pane.scrollTop).toBe(2000);
  });

  it("reveals new provisional speech rather than scrolling to the lingering assistant reply", () => {
    const { container, rerender } = render(<AvatarTranscriptPanel {...props} assistantReply="Old reply" />);
    const pane = screen.getByLabelText("滚动查看通话转写");
    Object.defineProperty(pane, 'scrollHeight', { value: 3000 });
    vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue({ top: 100 } as DOMRect);
    // Geometry comes from the browser in production; provide the new row's position here.
    const rect = vi.spyOn(HTMLDivElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({ top: 240 } as DOMRect);
    rerender(<AvatarTranscriptPanel {...props} userTranscript="Please wait" interim assistantReply="Old reply" />);
    expect(container.querySelector('.vsAvatarTranscriptTurn.interim p')).toHaveTextContent('Please wait');
    expect(pane.scrollTop).toBeLessThan(3000);
    expect(screen.getByText('Old reply')).toBeInTheDocument();
    rect.mockRestore();
  });
  it("follows the newest words when provisional input itself exceeds the pane", () => {
    const { rerender } = render(<AvatarTranscriptPanel {...props} assistantReply="Old reply" />);
    const pane = screen.getByLabelText("滚动查看通话转写");
    Object.defineProperties(pane, { scrollHeight: { value: 3000 }, clientHeight: { value: 400 } });
    vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue({ top: 100, bottom: 500, height: 400 } as DOMRect);
    const rect = vi.spyOn(HTMLDivElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({ top: 200, bottom: 1200, height: 1000 } as DOMRect);
    rerender(<AvatarTranscriptPanel {...props} userTranscript={'New speech. '.repeat(100)} interim assistantReply="Old reply" />);
    expect(pane.scrollTop).toBe(712);
    rect.mockRestore();
  });

});
