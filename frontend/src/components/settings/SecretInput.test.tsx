import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const revealSettingsSecret = vi.fn();
vi.mock("../../api/client", () => ({
  revealSettingsSecret: (...args: unknown[]) => revealSettingsSecret(...args),
}));

import SecretInput, { MASKED_SECRET } from "./SecretInput";

function getInput(): HTMLInputElement {
  return document.querySelector("input") as HTMLInputElement;
}

describe("SecretInput", () => {
  beforeEach(() => {
    revealSettingsSecret.mockReset();
  });

  it("drops a revealed secret when the field switches to another provider", async () => {
    revealSettingsSecret.mockResolvedValue("sk-dashscope-real");
    const onChange = vi.fn();
    const { rerender } = render(
      <SecretInput value={MASKED_SECRET} onChange={onChange} section="api_keys" secretKey="dashscope_api_key" />
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });
    expect(getInput().value).toBe("sk-dashscope-real");

    rerender(
      <SecretInput value={MASKED_SECRET} onChange={onChange} section="api_keys" secretKey="google_api_key" />
    );
    expect(getInput().value).toBe(MASKED_SECRET);
    expect(getInput().type).toBe("password");

    // Typing must never carry the previous provider's key into this field.
    fireEvent.change(getInput(), { target: { value: "x" } });
    expect(onChange).toHaveBeenLastCalledWith("x");
  });

  it("ignores a reveal response that arrives after the provider changed", async () => {
    let resolveReveal: (value: string) => void = () => {};
    revealSettingsSecret.mockReturnValue(new Promise<string>((resolve) => { resolveReveal = resolve; }));
    const { rerender } = render(
      <SecretInput value={MASKED_SECRET} onChange={vi.fn()} section="api_keys" secretKey="dashscope_api_key" />
    );

    fireEvent.click(screen.getByRole("button"));
    rerender(
      <SecretInput value={MASKED_SECRET} onChange={vi.fn()} section="api_keys" secretKey="google_api_key" />
    );
    await act(async () => {
      resolveReveal("sk-dashscope-real");
    });

    expect(getInput().value).toBe(MASKED_SECRET);
  });

  it("keeps the revealed value while the user edits the same secret", async () => {
    revealSettingsSecret.mockResolvedValue("sk-real");
    const onChange = vi.fn();
    const { rerender } = render(
      <SecretInput value={MASKED_SECRET} onChange={onChange} section="api_keys" secretKey="dashscope_api_key" />
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });

    fireEvent.change(getInput(), { target: { value: "sk-real2" } });
    rerender(
      <SecretInput value="sk-real2" onChange={onChange} section="api_keys" secretKey="dashscope_api_key" />
    );

    expect(onChange).toHaveBeenLastCalledWith("sk-real2");
    expect(getInput().value).toBe("sk-real2");
    expect(getInput().type).toBe("text");
  });
});
