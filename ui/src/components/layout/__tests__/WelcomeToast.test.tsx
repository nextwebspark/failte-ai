import { render } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WelcomeToast } from "../WelcomeToast";

const auth = vi.hoisted(() => ({
    value: { user: { name: "Mary Byrne" }, isAuthenticated: true, loading: false } as Record<string, unknown>,
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

describe("WelcomeToast", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        sessionStorage.clear();
        auth.value = { user: { name: "Mary Byrne" }, isAuthenticated: true, loading: false };
    });

    it("welcomes the person by name once, right after sign-in", () => {
        sessionStorage.setItem("lm-just-signed-in", "1");
        const { rerender } = render(<WelcomeToast />);
        rerender(<WelcomeToast />);
        expect(toast.success).toHaveBeenCalledTimes(1);
        expect(vi.mocked(toast.success).mock.calls[0][0]).toBe("Welcome back, Mary");
        expect(sessionStorage.getItem("lm-just-signed-in")).toBeNull();
    });

    it("welcomes someone who just signed up to the product", () => {
        sessionStorage.setItem("lm-just-signed-in", "new");
        render(<WelcomeToast />);
        const [title, options] = vi.mocked(toast.success).mock.calls[0];
        expect(title).toBe("Welcome to LightMove.ai, Mary!");
        expect(String((options as { description: string }).description)).toMatch(/workspace is ready/);
    });

    it("says a plain hello when we can't tell new from returning", () => {
        sessionStorage.setItem("lm-just-signed-in", "hello");
        render(<WelcomeToast />);
        expect(vi.mocked(toast.success).mock.calls[0][0]).toBe("Welcome, Mary");
    });

    it("ignores a flag it doesn't know", () => {
        sessionStorage.setItem("lm-just-signed-in", "surprise");
        render(<WelcomeToast />);
        expect(toast.success).not.toHaveBeenCalled();
    });

    it("stays quiet on ordinary page loads", () => {
        render(<WelcomeToast />);
        expect(toast.success).not.toHaveBeenCalled();
    });

    it("waits until the session is known", () => {
        sessionStorage.setItem("lm-just-signed-in", "1");
        auth.value = { user: null, isAuthenticated: false, loading: true };
        render(<WelcomeToast />);
        expect(toast.success).not.toHaveBeenCalled();
        expect(sessionStorage.getItem("lm-just-signed-in")).toBe("1");
    });
});
