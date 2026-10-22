import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ publish: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { promise: vi.fn(), error: vi.fn(), success: vi.fn() }) }));
vi.mock("@/client/sdk.gen", () => ({
    publishWorkflowApiV1WorkflowWorkflowIdPublishPost: mocks.publish,
    duplicateWorkflowEndpointApiV1WorkflowWorkflowIdDuplicatePost: vi.fn(),
}));

import { WorkflowEditorHeader } from "./WorkflowEditorHeader";

type Props = Parameters<typeof WorkflowEditorHeader>[0];

function renderHeader(overrides: Partial<Props> = {}) {
    const props: Props = {
        workflowName: "AI Receptionist · Bloom Dental",
        isDirty: false,
        workflowValidationErrors: [],
        rfInstance: { current: null },
        workflowId: 7,
        saveWorkflow: vi.fn(async () => {}),
        user: { id: "1" },
        onPhoneCallClick: vi.fn(),
        onHistoryClick: vi.fn(),
        activeVersionLabel: "v3 (Draft)",
        isViewingHistoricalVersion: false,
        onBackToDraft: vi.fn(),
        hasDraft: true,
        onPublished: vi.fn(),
        renameWorkflow: vi.fn(async () => {}),
        ...overrides,
    };
    render(<WorkflowEditorHeader {...props} />);
    return props;
}

describe("WorkflowEditorHeader", () => {
    it("renders its actions in one toolbar of its own", () => {
        renderHeader();
        const toolbar = screen.getByRole("group", { name: "Agent" });
        for (const name of [/Phone call/, "Save", "Publish", "More agent actions"]) {
            expect(toolbar.contains(screen.getByRole("button", { name }))).toBe(true);
        }
    });

    it("renames from the name itself", async () => {
        const props = renderHeader();

        fireEvent.click(screen.getByRole("button", { name: /Rename agent: AI Receptionist/ }));
        const input = screen.getByLabelText("Agent name");
        fireEvent.change(input, { target: { value: "Front desk" } });
        fireEvent.keyDown(input, { key: "Enter" });

        await waitFor(() => expect(props.renameWorkflow).toHaveBeenCalledWith("Front desk"));
    });

    it("says why Publish is unavailable", () => {
        renderHeader({ isDirty: true });
        expect(screen.getByText("Unsaved")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Publish" }).getAttribute("title")).toBe("Save first");
        expect(screen.getByRole("button", { name: /Phone call/ })).toHaveProperty("disabled", true);
    });

    it("has nothing to publish without a draft", () => {
        renderHeader({ hasDraft: false });
        const publish = screen.getByRole("button", { name: "Publish" });
        expect(publish).toHaveProperty("disabled", true);
        expect(publish.getAttribute("title")).toBe("Nothing new to publish");
    });

    it("publishes a saved, valid draft", async () => {
        mocks.publish.mockResolvedValue({ data: {} });
        const props = renderHeader();

        fireEvent.click(screen.getByRole("button", { name: "Publish" }));

        await waitFor(() => expect(props.onPublished).toHaveBeenCalled());
        expect(mocks.publish).toHaveBeenCalledWith({ path: { workflow_id: 7 } });
    });

    it("counts errors and blocks calling and publishing", () => {
        renderHeader({ workflowValidationErrors: [{ kind: "node", id: "n1", message: "No prompt" } as never] });
        expect(screen.getByText("1 error")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Publish" }).getAttribute("title")).toBe("Fix the errors first");
    });

    it("on an old version, offers only the way back", () => {
        const props = renderHeader({ isViewingHistoricalVersion: true, activeVersionLabel: "v1 (Published)" });
        expect(screen.getByText("Read only")).toBeTruthy();
        expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
        expect(screen.queryByRole("button", { name: /Rename agent/ })).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Back to draft" }));
        expect(props.onBackToDraft).toHaveBeenCalled();
    });
});
