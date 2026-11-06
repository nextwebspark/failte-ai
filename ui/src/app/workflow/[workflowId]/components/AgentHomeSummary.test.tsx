import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    agent: null as null | { id: number; name: string; versionStatus: string | null; totalRuns: number },
    openTester: vi.fn(),
    configs: vi.fn(),
    numbers: vi.fn(),
    runs: vi.fn(),
    can: vi.fn<(p: string) => boolean>(() => true),
    auth: { user: { id: "1" }, loading: false, getAccessToken: async () => "token" },
}));

vi.mock("@/context/AgentShellContext", () => ({
    useAgentShell: () => ({ agent: mocks.agent, loading: mocks.agent === null, openTester: mocks.openTester }),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, orgContext: {} }),
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({ useOrganizationTimezone: () => "Europe/Dublin" }));
vi.mock("@/client/sdk.gen", () => ({
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet: mocks.configs,
    listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet: mocks.numbers,
    getWorkflowRunsApiV1WorkflowWorkflowIdRunsGet: mocks.runs,
}));

import { AgentHomeSummary, agentStatusWords } from "./AgentHomeSummary";

const number = (address: string, agentId: number | null, active = true) => ({
    address,
    inbound_workflow_id: agentId,
    is_active: active,
});

describe("AgentHomeSummary", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.agent = { id: 14, name: "Bia Bistro bookings", versionStatus: "published", totalRuns: 0 };
        mocks.can.mockImplementation(() => true);
        mocks.configs.mockResolvedValue({ data: { configurations: [{ id: 1 }] } });
        mocks.numbers.mockResolvedValue({ data: { phone_numbers: [] } });
        mocks.runs.mockResolvedValue({ data: { runs: [] } });
    });

    it("shows a skeleton until the agent has loaded", () => {
        mocks.agent = null;
        render(<AgentHomeSummary workflowId={14} />);
        expect(screen.getByLabelText("Loading your agent").getAttribute("aria-busy")).toBe("true");
    });

    it("names the agent, says it is live and offers to talk to it", async () => {
        render(<AgentHomeSummary workflowId={14} />);
        expect(screen.getByRole("heading", { name: "Bia Bistro bookings" })).toBeTruthy();
        expect(screen.getByText("Live")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /talk to your agent/i }));
        expect(mocks.openTester).toHaveBeenCalled();
    });

    it("says when no phone number is connected, with a link to connect one", async () => {
        mocks.numbers.mockResolvedValue({ data: { phone_numbers: [number("+353 1 555 0100", 99)] } });
        render(<AgentHomeSummary workflowId={14} />);
        const link = await screen.findByRole("link", { name: /connect a phone number/i });
        expect(link.getAttribute("href")).toBe("/workflow/14/deployment#phone");
        expect(link.textContent).toContain("Not connected yet");
        // Another agent's number is never shown as this agent's.
        expect(screen.queryByText("+353 1 555 0100")).toBeNull();
    });

    it("shows the number that rings this agent", async () => {
        mocks.numbers.mockResolvedValue({
            data: { phone_numbers: [number("+353 1 555 0199", 14), number("+353 1 555 0100", 14, false)] },
        });
        render(<AgentHomeSummary workflowId={14} />);
        expect(await screen.findByText("+353 1 555 0199")).toBeTruthy();
        // A turned-off number doesn't ring anyone.
        expect(screen.queryByText(/and 1 more/)).toBeNull();
    });

    it("falls back to a plain link when the numbers can't be read", async () => {
        mocks.configs.mockResolvedValue({ error: { detail: "nope" } });
        render(<AgentHomeSummary workflowId={14} />);
        const link = await screen.findByRole("link", { name: /how callers reach it/i });
        expect(link.getAttribute("href")).toBe("/workflow/14/deployment");
        expect(screen.queryByText(/nope/)).toBeNull();
    });

    it("says there are no calls yet without asking for any", async () => {
        render(<AgentHomeSummary workflowId={14} />);
        expect(screen.getByText(/No calls yet/)).toBeTruthy();
        await waitFor(() => expect(mocks.numbers).toHaveBeenCalled());
        expect(mocks.runs).not.toHaveBeenCalled();
        expect(screen.queryByRole("heading", { name: "Recent calls" })).toBeNull();
    });

    it("lists recent calls as links when there are some", async () => {
        mocks.agent = { id: 14, name: "Bia", versionStatus: "published", totalRuns: 2 };
        mocks.runs.mockResolvedValue({
            data: {
                runs: [
                    { id: 7, mode: "smallwebrtc", call_type: "inbound", created_at: "2026-11-01T10:00:00Z", cost_info: { call_duration_seconds: 75 } },
                    { id: 6, mode: "twilio", call_type: "inbound", created_at: "2026-10-30T10:00:00Z", cost_info: {} },
                ],
            },
        });
        render(<AgentHomeSummary workflowId={14} />);
        expect(screen.getByText("2 calls so far.")).toBeTruthy();
        await screen.findByRole("heading", { name: "Recent calls" });
        const test = screen.getByRole("link", { name: /test call in the browser/i });
        expect(test.getAttribute("href")).toBe("/workflow/14/run/7");
        expect(test.textContent).toContain("1 min 15 sec");
        expect(screen.getByRole("link", { name: /incoming call/i }).getAttribute("href")).toBe("/workflow/14/run/6");
    });
});

describe("agentStatusWords", () => {
    it("uses plain words for each status", () => {
        expect(agentStatusWords("published").label).toBe("Live");
        expect(agentStatusWords("draft").label).toBe("Changes not live yet");
        expect(agentStatusWords(null).label).toBe("Not live yet");
    });
});
