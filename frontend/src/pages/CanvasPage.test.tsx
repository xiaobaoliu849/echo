import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import CanvasPage from "./CanvasPage";
import * as useCanvasModule from "../hooks/useCanvas";
import { createCanvasController } from "../test/factories";

vi.mock("../hooks/useCanvas", () => ({
  default: vi.fn()
}));

describe("CanvasPage", () => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  it("renders empty state", () => {
    vi.mocked(useCanvasModule.default).mockReturnValue(createCanvasController() as any);
    render(<CanvasPage />);
    expect(screen.getByText(/暂无代码|No code yet/i)).toBeInTheDocument();
  });

  it("submits prompt", () => {
    const generateMock = vi.fn();
    vi.mocked(useCanvasModule.default).mockReturnValue(
      createCanvasController({ generateFromPrompt: generateMock }) as any
    );
    render(<CanvasPage />);
    
    const input = screen.getByPlaceholderText(/描述你的界面|Describe your UI/i);
    fireEvent.change(input, { target: { value: "test ui" } });
    
    // Can't easily select the exact send button if no aria label, but let's try via icon/button
    // We can also fire enter
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", shiftKey: false });
    
    expect(generateMock).toHaveBeenCalledWith("test ui", []);
  });

  it("toggles views", () => {
    const setViewMock = vi.fn();
    vi.mocked(useCanvasModule.default).mockReturnValue(
      createCanvasController({ setActiveView: setViewMock, currentCode: "<div></div>", messages: [{ id: "1", role: "user", content: "test", timestamp: 123 }] }) as any
    );
    render(<CanvasPage />);
    
    const codeBtn = screen.getByText(/代码|Code/i);
    fireEvent.click(codeBtn);
    expect(setViewMock).toHaveBeenCalledWith("code");
  });
});
