import { act, fireEvent, render, screen } from "@testing-library/react";
import * as Babel from "@babel/standalone";
import * as React from "react";
import * as ReactDOM from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import CanvasPreview from "./CanvasPreview";

// Execute the preview's actual boot script with the same Babel version as its
// CDN runtime. jsdom does not execute iframe srcdoc scripts on its own.
function executePreview(code: string) {
  const view = render(<CanvasPreview code={code} mode="react" />);
  const frame = view.container.querySelector("iframe")!;
  const doc = new DOMParser().parseFromString(frame.srcdoc, "text/html");
  const scripts = Array.from(doc.querySelectorAll("script:not([src])"));
  expect(scripts).toHaveLength(1);
  const target = document.createElement("div");
  document.body.appendChild(target);
  const root = ReactDOM.createRoot(target);
  const postMessage = vi.fn();
  act(() => {
    new Function("Babel", "React", "ReactDOM", "window", "document", scripts[0].textContent!)(
      Babel, React, { createRoot: () => root },
      { parent: { postMessage }, addEventListener: vi.fn() },
      { getElementById: () => target },
    );
  });
  return {
    target, postMessage,
    dispose: () => { act(() => root.unmount()); target.remove(); view.unmount(); },
  };
}

describe("CanvasPreview React execution", () => {
  it.each([
    "export default function Cat() { return <h1>Canvas cat</h1>; }",
    "export default () => <h1>Canvas cat</h1>;",
    "const Cat = () => <h1>Canvas cat</h1>; export default Cat;",
    "function App() { return <h1>Canvas cat</h1>; }",
    "export function Cat() { return <h1>Canvas cat</h1>; }",
    "function Cat() { return <h1>Canvas cat</h1>; }",
    "const Cat = () => <h1>Canvas cat</h1>;",
  ])("renders supported component syntax: %s", code => {
    const preview = executePreview(code);
    try {
      expect(preview.target.textContent).toBe("Canvas cat");
      expect(preview.postMessage).not.toHaveBeenCalled();
    } finally { preview.dispose(); }
  });

  it.each([
    "import React, { useState } from 'react';",
    "const { useState } = React;",
    "",
  ])("runs interactive hooks with source prelude: %s", prelude => {
    const preview = executePreview(`
      ${prelude}
      export default function Counter() {
        const [count, setCount] = useState(0);
        return <button onClick={() => setCount(count + 1)}>{count}</button>;
      }
    `);
    try {
      const button = preview.target.querySelector("button")!;
      fireEvent.click(button);
      expect(button.textContent).toBe("1");
      expect(preview.postMessage).not.toHaveBeenCalled();
    } finally { preview.dispose(); }
  });

  it("keeps literal closing script tags inside the generated component", () => {
    const preview = executePreview(`export default () => <pre>{"</script><h1>Literal</h1>"}</pre>;`);
    try {
      expect(preview.target.textContent).toBe("</script><h1>Literal</h1>");
      expect(preview.target.querySelector("h1")).toBeNull();
    } finally { preview.dispose(); }
  });

  it.each([
    "export default function Broken( {",
    "import Missing from 'unknown-package'; export default Missing;",
    "const noComponent = 123;",
  ])("reports compilation or module errors: %s", code => {
    const preview = executePreview(code);
    try {
      expect(preview.postMessage).toHaveBeenCalledWith(
        { type: "CANVAS_ERROR", message: expect.any(String) }, "*",
      );
      expect(preview.target.textContent).toMatch(/^Error:/);
    } finally { preview.dispose(); }
  });

  it("accepts errors only from its current iframe and resets on mode change", () => {
    const view = render(<CanvasPreview code="test" mode="react" />);
    const frame = view.container.querySelector("iframe")!;
    const data = { type: "CANVAS_ERROR", message: "bad component" };
    act(() => window.dispatchEvent(new MessageEvent("message", { data, source: window })));
    expect(screen.queryByText(/bad component/)).not.toBeInTheDocument();
    act(() => window.dispatchEvent(new MessageEvent("message", { data, source: frame.contentWindow })));
    expect(screen.getByText(/bad component/)).toBeInTheDocument();
    view.rerender(<CanvasPreview code="test" mode="html" />);
    expect(screen.queryByText(/bad component/)).not.toBeInTheDocument();
    expect(view.container.querySelector("iframe")!.getAttribute("sandbox")).toBe("allow-scripts");
  });
});
