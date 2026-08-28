import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthDialog from "./AuthDialog";
import { ApiRequestError, type AuthRuntimeConfig } from "../api";

const changeAuthPassword = vi.fn();
const revokeOtherAuthSessions = vi.fn();

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    changeAuthPassword: (...args: unknown[]) => changeAuthPassword(...args),
    revokeOtherAuthSessions: (...args: unknown[]) => revokeOtherAuthSessions(...args),
  };
});

const SIGNED_IN_AUTH: AuthRuntimeConfig = {
  apiToken: "token-1",
  adminToken: "",
  userEmail: "user@example.com",
  isAdmin: false,
  hasEnvApiToken: false,
  hasEnvAdminToken: false,
};

const GUEST_AUTH: AuthRuntimeConfig = {
  apiToken: "",
  adminToken: "",
  userEmail: "",
  isAdmin: false,
  hasEnvApiToken: false,
  hasEnvAdminToken: false,
};

function renderSignedIn() {
  return render(
    <AuthDialog
      open
      auth={SIGNED_IN_AUTH}
      onClose={() => {}}
      onLogin={vi.fn().mockResolvedValue(undefined)}
      onRegister={vi.fn().mockResolvedValue(undefined)}
      onLogout={() => {}}
    />
  );
}

function openChangePasswordForm() {
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }));
}

beforeEach(() => {
  changeAuthPassword.mockReset();
  revokeOtherAuthSessions.mockReset();
});

describe("AuthDialog account management", () => {
  it("changes password with entered values and shows success", async () => {
    changeAuthPassword.mockResolvedValue({ id: "1", email: "user@example.com" });
    renderSignedIn();
    openChangePasswordForm();

    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "old-pass-1" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "new-pass-1" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "new-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => {
      expect(changeAuthPassword).toHaveBeenCalledWith("old-pass-1", "new-pass-1");
    });
    expect(
      await screen.findByText("密码已更新，其他设备已自动退出。")
    ).toBeInTheDocument();
  });

  it("blocks submission when new passwords do not match", async () => {
    renderSignedIn();
    openChangePasswordForm();

    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "old-pass-1" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "new-pass-1" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "other-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    expect(screen.getByText("两次输入的新密码不一致。")).toBeInTheDocument();
    expect(changeAuthPassword).not.toHaveBeenCalled();
  });

  it("shows lockout wait time when the API rate limits the change", async () => {
    changeAuthPassword.mockRejectedValue(
      new ApiRequestError("AUTH_RATE_LIMITED: Too many attempts.", 429, {
        code: "AUTH_RATE_LIMITED",
        message: "Too many attempts.",
        meta: { retry_after: 30 },
      })
    );
    renderSignedIn();
    openChangePasswordForm();

    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "old-pass-1" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "new-pass-1" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "new-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    expect(
      await screen.findByText("尝试过于频繁，请 30 秒后重试。")
    ).toBeInTheDocument();
  });

  it("revokes other sessions and reports the count", async () => {
    revokeOtherAuthSessions.mockResolvedValue(2);
    renderSignedIn();

    fireEvent.click(screen.getByRole("button", { name: "退出其他设备" }));

    expect(await screen.findByText("已退出其他 2 个会话。")).toBeInTheDocument();
  });

  it("reports when there are no other active sessions", async () => {
    revokeOtherAuthSessions.mockResolvedValue(0);
    renderSignedIn();

    fireEvent.click(screen.getByRole("button", { name: "退出其他设备" }));

    expect(await screen.findByText("没有其他活跃会话。")).toBeInTheDocument();
  });
});

describe("AuthDialog login rate limiting", () => {
  it("shows lockout wait time when login is rate limited", async () => {
    const onLogin = vi
      .fn()
      .mockRejectedValue(
        new ApiRequestError("AUTH_RATE_LIMITED: Account locked.", 429, {
          code: "AUTH_RATE_LIMITED",
          message: "Account locked.",
          meta: { retry_after: 45 },
        })
      );
    render(
      <AuthDialog
        open
        auth={GUEST_AUTH}
        onClose={() => {}}
        onLogin={onLogin}
        onRegister={vi.fn().mockResolvedValue(undefined)}
        onLogout={() => {}}
      />
    );

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "whatever" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("尝试过于频繁，请 45 秒后重试。")).toBeInTheDocument();
  });
});
