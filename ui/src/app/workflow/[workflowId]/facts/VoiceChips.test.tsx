import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceChips } from "./VoiceChips";
import type { VoiceChoices } from "./voiceOptions";

const preview = vi.hoisted(() => ({ toggle: vi.fn(), playingId: null as string | null, previewError: null as string | null }));
vi.mock("@/hooks/useVoicePreview", () => ({
    useVoicePreview: () => ({ ...preview, stop: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CHOICES: VoiceChoices = {
    current: { value: "Charon", name: "Charon", gender: "Male", style: "Informative", previewVoiceId: "en-US-Chirp3-HD-Charon" },
    alternatives: [
        { value: "Kore", name: "Kore", gender: "Female", style: "Firm", previewVoiceId: "en-US-Chirp3-HD-Kore" },
        { value: "Puck", name: "Puck", gender: "Male", style: "Upbeat", previewVoiceId: "en-US-Chirp3-HD-Puck" },
    ],
};

describe("VoiceChips", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        preview.playingId = null;
        preview.previewError = null;
        preview.toggle.mockResolvedValue(undefined);
    });

    it("plays nothing until asked, then reads the greeting in the chosen voice", async () => {
        render(<VoiceChips workflowId={12} choices={CHOICES} readsGreeting />);
        expect(preview.toggle).not.toHaveBeenCalled();
        expect(screen.getByText("Charon · Male")).toBeTruthy();
        expect(screen.getByText(/Your agent's voice/)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Hear Kore read your greeting" }));
        await waitFor(() =>
            expect(preview.toggle).toHaveBeenCalledWith("Kore", "/api/v1/workflow/12/voice-preview?voice_id=en-US-Chirp3-HD-Kore"),
        );
    });

    it("says when the voices read a sample instead of the greeting", () => {
        render(<VoiceChips workflowId={12} choices={CHOICES} readsGreeting={false} />);
        expect(screen.getByRole("button", { name: "Hear Charon read a sample sentence" })).toBeTruthy();
        expect(screen.getByText(/short sample sentence/)).toBeTruthy();
    });

    it("is listen-only for members who can't change the agent", () => {
        render(<VoiceChips workflowId={12} choices={CHOICES} readsGreeting />);
        expect(screen.queryByRole("button", { name: /^Use / })).toBeNull();
        expect(screen.queryByText(/Choose a name to switch/)).toBeNull();
    });

    it("switches the voice only after confirming", async () => {
        const onSwitch = vi.fn().mockResolvedValue(undefined);
        render(<VoiceChips workflowId={12} choices={CHOICES} readsGreeting onSwitch={onSwitch} />);
        fireEvent.click(screen.getByRole("button", { name: "Use Kore, female" }));
        expect(onSwitch).not.toHaveBeenCalled();
        expect(screen.getByText(/phone calls switch when the agent is next published/)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Use Kore" }));
        await waitFor(() => expect(onSwitch).toHaveBeenCalledWith("Kore"));
        expect(toast.success).toHaveBeenCalled();
        expect(screen.queryByRole("group", { name: "Change the voice" })).toBeNull();
    });

    it("keeps the choice open and says why when the switch fails", async () => {
        const onSwitch = vi.fn().mockRejectedValue(new Error("Not allowed"));
        render(<VoiceChips workflowId={12} choices={CHOICES} readsGreeting onSwitch={onSwitch} />);
        fireEvent.click(screen.getByRole("button", { name: "Use Puck, male" }));
        fireEvent.click(screen.getByRole("button", { name: "Use Puck" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Not allowed"));
        expect(screen.getByRole("group", { name: "Change the voice" })).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
        expect(screen.queryByRole("group", { name: "Change the voice" })).toBeNull();
    });

    it("shows when a sample can't play", () => {
        preview.previewError = "Preview unavailable for this voice";
        render(<VoiceChips workflowId={12} choices={CHOICES} readsGreeting />);
        expect(screen.getByRole("alert").textContent).toContain("Couldn't play that voice");
    });
});
