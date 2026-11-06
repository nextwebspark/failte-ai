import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BusinessFactsPage from "./page";

const mocks = vi.hoisted(() => ({
    get: vi.fn(),
    put: vi.fn(),
    can: vi.fn<(p: string) => boolean>(() => true),
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ workflowId: "12" }) }));
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
        mocks.can.mockImplementation(() => true);
        mocks.get.mockResolvedValue({ data: { facts: FACTS } });
        mocks.put.mockImplementation(async ({ body }) => ({
            data: { facts: FACTS.map((f) => ({ ...f, value: body.facts[f.key] ?? f.value })) },
        }));
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
});
