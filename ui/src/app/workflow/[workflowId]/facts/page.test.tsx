import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BusinessFactsPage from "./page";

const mocks = vi.hoisted(() => ({
    get: vi.fn(),
    put: vi.fn(),
    can: vi.fn<(p: string) => boolean>(() => true),
    query: "",
    replace: vi.fn(),
    openTester: vi.fn(),
}));

vi.mock("next/navigation", () => ({
    useParams: () => ({ workflowId: "12" }),
    useSearchParams: () => new URLSearchParams(mocks.query),
    usePathname: () => "/workflow/12/facts",
    useRouter: () => ({ replace: mocks.replace }),
}));
vi.mock("@/context/AgentShellContext", () => ({ useAgentShell: () => ({ openTester: mocks.openTester }) }));
// The summary has its own tests; here it only needs to be on the page.
vi.mock("../components/AgentHomeSummary", () => ({
    AgentHomeSummary: ({ workflowId }: { workflowId: number }) => <div data-testid="summary">agent {workflowId}</div>,
}));
vi.mock("@/client/sdk.gen", () => ({
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet: mocks.get,
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut: mocks.put,
}));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ can: mocks.can }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const FACTS = [
    { key: "opening_hours", label: "Opening hours", type: "text", required: true, max_length: 300, value: "Tue-Sun 12-22" },
    { key: "extra_info", label: "Anything else callers often ask?", type: "textarea", required: false, max_length: 1500, value: "" },
];

describe("Business facts", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.query = "";
        mocks.can.mockImplementation(() => true);
        mocks.get.mockResolvedValue({ data: { facts: FACTS } });
        mocks.put.mockImplementation(async ({ body }) => ({
            data: { facts: FACTS.map((f) => ({ ...f, value: body.facts[f.key] ?? f.value })) },
        }));
    });

    it("puts the agent summary above the facts", async () => {
        render(<BusinessFactsPage />);
        const summary = screen.getByTestId("summary");
        expect(summary.textContent).toBe("agent 12");
        const heading = await screen.findByRole("heading", { name: "Business facts" });
        expect(summary.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("opens the test panel once when arriving from the Create agent wizard", async () => {
        mocks.query = "onboarding=web_call";
        render(<BusinessFactsPage />);
        await screen.findByLabelText("Opening hours");
        expect(mocks.openTester).toHaveBeenCalledTimes(1);
        expect(mocks.replace).toHaveBeenCalledWith("/workflow/12/facts", { scroll: false });
    });

    it("leaves the test panel alone on a normal visit", async () => {
        render(<BusinessFactsPage />);
        await screen.findByLabelText("Opening hours");
        expect(mocks.openTester).not.toHaveBeenCalled();
        expect(mocks.replace).not.toHaveBeenCalled();
    });

    it("lets the owner change what the agent tells callers", async () => {
        render(<BusinessFactsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        expect((hours as HTMLInputElement).value).toBe("Tue-Sun 12-22");
        const save = screen.getByRole("button", { name: "Save changes" });
        expect(save.hasAttribute("disabled")).toBe(true);

        fireEvent.change(hours, { target: { value: "Wed-Sun 17-23" } });
        fireEvent.click(save);

        await waitFor(() =>
            expect(mocks.put).toHaveBeenCalledWith({
                path: { workflow_id: 12 },
                body: { facts: { opening_hours: "Wed-Sun 17-23" } },
            }),
        );
    });

    it("is read-only for people who can't edit facts", async () => {
        mocks.can.mockImplementation(() => false);
        render(<BusinessFactsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        expect(hours.hasAttribute("disabled")).toBe(true);
        expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
        expect(screen.getByText("Only the owner or an admin can change these.")).toBeTruthy();
    });

    it("explains agents without facts", async () => {
        mocks.get.mockResolvedValue({ data: { facts: [] } });
        render(<BusinessFactsPage />);
        expect(await screen.findByText("This agent has no business facts to edit here.")).toBeTruthy();
    });

    it("shows a load error with Try again, then recovers", async () => {
        mocks.get.mockResolvedValueOnce({ error: { detail: "Agent not found" } });
        render(<BusinessFactsPage />);
        const alert = await screen.findByRole("alert");
        expect(alert.textContent).toContain("We couldn't load your business facts");
        expect(alert.textContent).not.toContain("Agent not found");
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        expect(await screen.findByLabelText("Opening hours")).toBeTruthy();
        expect(mocks.get).toHaveBeenCalledTimes(2);
    });

    it("handles a network failure while loading", async () => {
        mocks.get.mockRejectedValueOnce(new TypeError("Failed to fetch"));
        render(<BusinessFactsPage />);
        expect((await screen.findByRole("alert")).textContent).toContain("We couldn't load your business facts");
        expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    });

    it("won't save a required answer left blank, and says which", async () => {
        render(<BusinessFactsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        expect(hours.hasAttribute("required")).toBe(true);
        fireEvent.change(hours, { target: { value: "   " } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        expect(mocks.put).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith("Fill in the required answers before saving.");
        expect(hours.getAttribute("aria-invalid")).toBe("true");
        const message = document.getElementById(hours.getAttribute("aria-describedby") ?? "");
        expect(message?.textContent).toContain("Your agent needs this answer");

        // Fixing it clears the message and saves.
        fireEvent.change(hours, { target: { value: "Mon-Fri 9-5" } });
        expect(hours.getAttribute("aria-invalid")).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    });

    it("lets an optional answer be blank", async () => {
        render(<BusinessFactsPage />);
        const extra = await screen.findByLabelText(/Anything else callers often ask/);
        fireEvent.change(extra, { target: { value: "Parking at the back" } });
        fireEvent.change(extra, { target: { value: "" } });
        fireEvent.change(screen.getByLabelText("Opening hours"), { target: { value: "Mon-Fri 9-5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() =>
            expect(mocks.put).toHaveBeenCalledWith({
                path: { workflow_id: 12 },
                body: { facts: { opening_hours: "Mon-Fri 9-5" } },
            }),
        );
    });

    it("sends only one save on a double click", async () => {
        let resolve: (value: unknown) => void = () => {};
        mocks.put.mockReturnValue(new Promise((r) => (resolve = r)));
        render(<BusinessFactsPage />);
        fireEvent.change(await screen.findByLabelText("Opening hours"), { target: { value: "Mon-Fri 9-5" } });
        const save = screen.getByRole("button", { name: "Save changes" });
        fireEvent.click(save);
        fireEvent.click(save);
        expect(mocks.put).toHaveBeenCalledTimes(1);
        expect(screen.getByRole("button", { name: "Saving…" }).hasAttribute("disabled")).toBe(true);
        resolve({ data: { facts: FACTS.map((f) => (f.key === "opening_hours" ? { ...f, value: "Mon-Fri 9-5" } : f)) } });
        await waitFor(() => expect(toast.success).toHaveBeenCalled());
    });

    it("keeps the owner's typing when the save is refused", async () => {
        mocks.put.mockResolvedValue({ error: { detail: "Opening hours is too long." } });
        render(<BusinessFactsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        fireEvent.change(hours, { target: { value: "Mon-Fri 9-5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Opening hours is too long."));
        expect((hours as HTMLInputElement).value).toBe("Mon-Fri 9-5");
        expect(screen.getByRole("button", { name: "Save changes" }).hasAttribute("disabled")).toBe(false);
    });

    it("handles a network failure while saving", async () => {
        mocks.put.mockRejectedValue(new TypeError("Failed to fetch"));
        render(<BusinessFactsPage />);
        fireEvent.change(await screen.findByLabelText("Opening hours"), { target: { value: "Mon-Fri 9-5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't save. Please try again."));
        expect(screen.getByRole("button", { name: "Save changes" }).hasAttribute("disabled")).toBe(false);
    });

    it("Undo puts the saved answers back", async () => {
        render(<BusinessFactsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        fireEvent.change(hours, { target: { value: "Closed" } });
        fireEvent.click(screen.getByRole("button", { name: "Undo" }));
        expect((hours as HTMLInputElement).value).toBe("Tue-Sun 12-22");
        expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    });
});
