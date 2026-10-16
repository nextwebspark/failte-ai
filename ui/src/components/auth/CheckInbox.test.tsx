import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CheckInbox } from "./CheckInbox";

const mocks = vi.hoisted(() => ({
  verifyCode: vi.fn(),
  resend: vi.fn(),
  startLocalSession: vi.fn(),
}));

vi.mock("@/client/sdk.gen", () => ({
  verifyEmailCodeApiV1AuthVerifyEmailCodePost: mocks.verifyCode,
  resendVerificationApiV1AuthResendVerificationPost: mocks.resend,
}));

vi.mock("@/lib/auth/localSession", () => ({
  startLocalSession: mocks.startLocalSession,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const session = { token: "jwt", user: { id: 1, email: "pat@example.com" } };

function codeInput() {
  return screen.getByLabelText("Verification code") as HTMLInputElement;
}

describe("CheckInbox", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.verifyCode.mockResolvedValue({ data: session });
    mocks.resend.mockResolvedValue({ data: undefined });
  });

  it("keeps only the digits of a pasted code and verifies it", async () => {
    render(<CheckInbox email="pat@example.com" nextPath="/workflow" />);
    const submit = screen.getByRole("button", { name: "Verify email" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(codeInput(), { target: { value: "123 456" } });
    expect(codeInput().value).toBe("123456");
    fireEvent.click(submit);

    await waitFor(() =>
      expect(mocks.verifyCode).toHaveBeenCalledWith({
        body: { email: "pat@example.com", code: "123456" },
      }),
    );
    expect(mocks.startLocalSession).toHaveBeenCalledWith(session, "/workflow");
  });

  it("shows the API's message for a wrong code and stays on the page", async () => {
    mocks.verifyCode.mockResolvedValue({
      error: { detail: "That code is incorrect or has expired.", code: "invalid_verification_code" },
    });
    render(<CheckInbox email="pat@example.com" />);

    fireEvent.change(codeInput(), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify email" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "That code is incorrect or has expired.",
    );
    expect(mocks.startLocalSession).not.toHaveBeenCalled();
  });

  it("sends a new code and clears the field", async () => {
    render(<CheckInbox email="pat@example.com" />);
    fireEvent.change(codeInput(), { target: { value: "999999" } });

    fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));

    await waitFor(() =>
      expect(mocks.resend).toHaveBeenCalledWith({ body: { email: "pat@example.com" } }),
    );
    await waitFor(() => expect(codeInput().value).toBe(""));
    expect(toast.success).toHaveBeenCalled();
  });
});
