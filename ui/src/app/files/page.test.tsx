import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FilesPage from "./page";

const mocks = vi.hoisted(() => ({
    auth: { user: { id: 1 }, loading: false, redirectToLogin: vi.fn() },
    config: { documentProcessingEnabled: true, mpsEnabled: false },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/context/AppConfigContext", () => ({
    useAppConfig: () => ({ config: mocks.config, loading: false }),
}));
vi.mock("@/components/layout/PageActionsSlot", () => ({
    PageActions: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("./DocumentList", () => ({ default: () => null }));
vi.mock("./DocumentUpload", () => ({ default: () => null }));

beforeEach(() => {
    mocks.config.documentProcessingEnabled = true;
    mocks.config.mpsEnabled = false;
});

describe("knowledge base uploads", () => {
    it("are offered without an MPS, since documents are processed on the server", () => {
        render(<FilesPage />);
        expect(screen.getByRole("button", { name: "Upload document" })).toBeTruthy();
        expect(screen.queryByText(/isn.t available yet/)).toBeNull();
    });

    it("are hidden when the backend can't process documents", () => {
        mocks.config.documentProcessingEnabled = false;
        render(<FilesPage />);
        expect(screen.queryByRole("button", { name: "Upload document" })).toBeNull();
        expect(screen.getByText(/Document processing isn.t available yet/)).toBeTruthy();
    });
});
