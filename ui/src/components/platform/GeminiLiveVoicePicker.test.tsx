import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GeminiLiveVoicePicker } from "@/components/platform/GeminiLiveVoicePicker";
import { platformCatalogFixture as catalog } from "@/lib/__fixtures__/platformCatalog";

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ getAccessToken: async () => "token" }) }));
vi.mock("@/lib/apiClient", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/lib/apiClient")>()),
    resolveBrowserBackendUrl: () => "http://api",
}));

const play = vi.fn().mockResolvedValue(undefined);
class FakeAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(public src: string) {}
    play = play;
    pause = vi.fn();
}

afterEach(() => {
    vi.unstubAllGlobals();
    play.mockClear();
});

describe("GeminiLiveVoicePicker", () => {
    it("selects a voice and shows its traits", () => {
        const onChange = vi.fn();
        render(<GeminiLiveVoicePicker voices={catalog.realtime.voices} value="Charon" onChange={onChange} />);

        expect(screen.getByRole("radio", { name: /Charon/ }).getAttribute("aria-checked")).toBe("true");
        expect(screen.getByText("Female · Firm")).toBeTruthy();
        fireEvent.click(screen.getByRole("radio", { name: /Kore/ }));
        expect(onChange).toHaveBeenCalledWith("Kore");
    });

    it("plays an authenticated sample only for voices that have one", async () => {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
        vi.stubGlobal("fetch", fetchMock);
        vi.stubGlobal("Audio", FakeAudio);
        vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:1", revokeObjectURL: vi.fn() });
        render(<GeminiLiveVoicePicker voices={catalog.realtime.voices} value="Charon" onChange={vi.fn()} />);

        expect(screen.queryByRole("button", { name: "Play Kore sample" })).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Play Charon sample" }));

        await waitFor(() => expect(play).toHaveBeenCalledOnce());
        expect(fetchMock).toHaveBeenCalledWith(
            "http://api/api/v1/user/configurations/voices/google/preview?voice_id=en-US-Chirp3-HD-Charon",
            { headers: { Authorization: "Bearer token" } },
        );
    });

    it("reports a failed sample", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
        render(<GeminiLiveVoicePicker voices={catalog.realtime.voices} value="Charon" onChange={vi.fn()} />);

        fireEvent.click(screen.getByRole("button", { name: "Play Charon sample" }));

        expect(await screen.findByText("Preview unavailable for this voice")).toBeTruthy();
    });
    it("filters by gender and keeps the selection visible in the summary", () => {
        render(<GeminiLiveVoicePicker voices={catalog.realtime.voices} value="Charon" onChange={vi.fn()} />);

        expect(screen.getByText("Charon", { selector: "span.font-medium.text-foreground" })).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /^Female/ }));
        expect(screen.queryByRole("radio", { name: /Charon/ })).toBeNull();
        expect(screen.getByRole("radio", { name: /Kore/ })).toBeTruthy();
        expect(screen.getByText(/Charon is selected but hidden by the filter/)).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /^All/ }));
        expect(screen.getByRole("radio", { name: /Charon/ })).toBeTruthy();
    });

    it("plays a sample without selecting the voice, and stops it again", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) }));
        vi.stubGlobal("Audio", FakeAudio);
        vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:1", revokeObjectURL: vi.fn() });
        const onChange = vi.fn();
        render(<GeminiLiveVoicePicker voices={catalog.realtime.voices} value="Kore" onChange={onChange} />);

        fireEvent.click(screen.getByRole("button", { name: "Play Charon sample" }));
        await waitFor(() => expect(screen.getByRole("button", { name: "Stop Charon sample" })).toBeTruthy());
        expect(onChange).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole("button", { name: "Stop Charon sample" }));
        expect(screen.getByRole("button", { name: "Play Charon sample" })).toBeTruthy();
    });
});
