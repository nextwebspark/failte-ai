import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    fetch: vi.fn(),
    auth: { user: { id: "1" }, loading: false, redirectToLogin: vi.fn() },
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ workflowId: "14" }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({ getWorkflowApiV1WorkflowFetchWorkflowIdGet: mocks.fetch }));
vi.mock("@/context/UnsavedChangesContext", () => ({
    UnsavedChangesProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../hooks/useWorkflowState", () => ({
    useWorkflowState: () => ({ workflowName: "Bia", workflowConfigurations: {} }),
}));
vi.mock("@/types/workflow-configurations", () => ({
    resolveWorkflowConfigurations: (c: unknown) => c,
}));

import { AgentSectionShell } from "./AgentSectionShell";

const WORKFLOW = { id: 14, name: "Bia", workflow_definition: { nodes: [], edges: [] } };

function renderShell() {
    return render(<AgentSectionShell>{({ workflowName }) => <p>Section for {workflowName}</p>}</AgentSectionShell>);
}

describe("AgentSectionShell", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("shows a skeleton, then the section", async () => {
        mocks.fetch.mockResolvedValue({ data: WORKFLOW });
        renderShell();
        expect(screen.getByLabelText("Loading").getAttribute("aria-busy")).toBe("true");
        expect(await screen.findByText("Section for Bia")).toBeTruthy();
    });

    it("says it couldn't load, without the raw error, and tries again", async () => {
        mocks.fetch.mockResolvedValueOnce({ error: { detail: "boom" }, response: { status: 500 } });
        mocks.fetch.mockResolvedValueOnce({ data: WORKFLOW });
        renderShell();
        const alert = await screen.findByRole("alert");
        expect(alert.textContent).toContain("We couldn't load this agent");
        expect(alert.textContent).not.toContain("boom");
        fireEvent.click(screen.getByRole("button", { name: /try again/i }));
        expect(await screen.findByText("Section for Bia")).toBeTruthy();
    });

    it("explains a missing agent", async () => {
        mocks.fetch.mockResolvedValue({ error: { detail: "Not found" }, response: { status: 404 } });
        renderShell();
        expect((await screen.findByRole("alert")).textContent).toContain("We couldn't find this agent");
        expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
    });
});
