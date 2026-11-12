import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
}));

vi.mock("@/client/sdk.gen", () => ({
    getCustomVoiceApiV1WorkflowWorkflowIdCustomVoiceGet: mocks.get,
    requestCustomVoiceApiV1WorkflowWorkflowIdCustomVoicePost: mocks.post,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { CustomVoice } from "./CustomVoice";

describe("CustomVoice", () => {
    beforeEach(() => {
        mocks.get.mockReset();
        mocks.post.mockReset();
    });

    it("says custom voices are coming soon and sends a request only with a voice ID and consent", async () => {
        mocks.get.mockResolvedValue({ data: { request: null } });
        mocks.post.mockResolvedValue({
            data: {
                request: {
                    workflow_id: 14,
                    provider: "elevenlabs",
                    voice_id: "abc123",
                    voice_name: "Pat",
                    requested_at: "2026-11-07T10:00:00Z",
                    status: "requested",
                },
            },
        });
        render(<CustomVoice workflowId={14} canRequest />);
        expect(screen.getByText("Coming soon")).toBeTruthy();

        fireEvent.click(await screen.findByRole("button", { name: "I already have a cloned voice" }));
        const send = screen.getByRole("button", { name: "Send request" }) as HTMLButtonElement;
        expect(send.disabled).toBe(true);

        fireEvent.change(screen.getByLabelText("Voice ID"), { target: { value: "abc123" } });
        expect(send.disabled).toBe(true);
        fireEvent.click(screen.getByRole("checkbox"));
        expect(send.disabled).toBe(false);

        fireEvent.click(send);
        await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
        expect(mocks.post.mock.calls[0][0].body).toMatchObject({ provider: "elevenlabs", voice_id: "abc123", consent: true });
        expect(await screen.findByText(/You asked us on 7 November to set up "Pat"/)).toBeTruthy();
    }, 20_000);

    it("shows no request button to someone who can't change the agent", async () => {
        mocks.get.mockResolvedValue({ data: { request: null } });
        render(<CustomVoice workflowId={14} canRequest={false} />);
        await waitFor(() => expect(mocks.get).toHaveBeenCalled());
        expect(screen.queryByRole("button", { name: "I already have a cloned voice" })).toBeNull();
    });
});
