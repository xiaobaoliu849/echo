import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import ErrorBoundary from "./ErrorBoundary";

function Boom(): ReactElement {
  throw new Error("render boom");
}

describe("ErrorBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <div>healthy content</div>
      </ErrorBoundary>
    );
    expect(screen.getByText("healthy content")).toBeInTheDocument();
  });

  it("shows the recovery screen when a child throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByText("界面渲染出错了")).toBeInTheDocument();
    expect(screen.getByText(/render boom/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重新加载/ })).toBeInTheDocument();
  });

  it("retry re-mounts the children and recovers", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    // Mutable flag in closure: the child throws until the test flips it,
    // regardless of how many times React re-invokes the render function.
    let shouldThrow = true;
    function ToggleChild(): ReactElement {
      if (shouldThrow) {
        throw new Error("boom once");
      }
      return <div>recovered content</div>;
    }

    render(
      <ErrorBoundary>
        <ToggleChild />
      </ErrorBoundary>
    );
    expect(screen.getByText("界面渲染出错了")).toBeInTheDocument();

    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: /重试/ }));
    expect(screen.getByText("recovered content")).toBeInTheDocument();
  });
});
