import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlatformTtsVoicePicker } from "@/components/platform/PlatformTtsVoicePicker";

const getVoices = vi.hoisted(() => vi.fn());
vi.mock("@/client/sdk.gen", () => ({ getVoicesApiV1UserConfigurationsVoicesProviderGet: getVoices }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ getAccessToken: async () => "token" }) }));

const voice = (voice_id: string, name: string, gender: string) => ({
    voice_id,
    name,
    gender,
    preview_url: `/api/v1/user/configurations/voices/google/preview?voice_id=${voice_id}`,
});

describe("PlatformTtsVoicePicker", () => {
    it("shows the voice language's voices as cards with samples and styles", async () => {
        getVoices.mockResolvedValue({
            data: {
                voices: [
                    voice("en-GB-Chirp3-HD-Kore", "Kore", "female"),
                    voice("en-GB-Chirp3-HD-Charon", "Charon", "male"),
                    // Another accent the API may also return for "en".
                    voice("en-AU-Chirp3-HD-Kore", "Kore", "female"),
                ],
            },
        });
        const onChange = vi.fn();
        render(
            <PlatformTtsVoicePicker
                catalog="google"
                model="chirp_3_hd"
                language="en-GB"
                value="en-GB-Chirp3-HD-Kore"
                onChange={onChange}
                styles={[{ id: "Kore", label: "Kore", description: "Firm" }]}
            />,
        );

        const kore = await screen.findByRole("radio", { name: /Kore/ });
        expect(kore.getAttribute("aria-checked")).toBe("true");
        expect(screen.getAllByRole("radio")).toHaveLength(2);
        expect(screen.getByText("Female · Firm")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Play Charon sample" })).toBeTruthy();
        expect(getVoices).toHaveBeenCalledWith({
            path: { provider: "google" },
            query: { model: "chirp_3_hd", language: "en", accent: "gb" },
        });

        fireEvent.click(screen.getByRole("radio", { name: /Charon/ }));
        expect(onChange).toHaveBeenCalledWith("en-GB-Chirp3-HD-Charon");
    });

    it("says when the voices can't be loaded", async () => {
        getVoices.mockResolvedValue({ error: { detail: "boom" } });
        render(
            <PlatformTtsVoicePicker catalog="google" model="chirp_3_hd" language="en-GB" value="" onChange={vi.fn()} />,
        );
        expect(await screen.findByText(/Couldn't load the voices/)).toBeTruthy();
    });
});
