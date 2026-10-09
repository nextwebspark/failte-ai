import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlatformTtsVoicePicker } from "@/components/platform/PlatformTtsVoicePicker";

const modal = vi.hoisted(() => ({ props: null as null | Record<string, unknown> }));

vi.mock("@/components/VoiceSelectorModal", () => ({
    ALL_FILTER_VALUE: "__all__",
    VoiceSelectorModal: (props: Record<string, unknown>) => {
        modal.props = props;
        return null;
    },
}));

describe("PlatformTtsVoicePicker", () => {
    it("opens the Google catalog on the voice language, any gender", () => {
        const onChange = vi.fn();
        render(
            <PlatformTtsVoicePicker
                catalog="google"
                model="chirp_3_hd"
                language="en-GB"
                value="en-GB-Chirp3-HD-Kore"
                onChange={onChange}
            />,
        );

        expect(modal.props).toMatchObject({
            provider: "google",
            model: "chirp_3_hd",
            value: "en-GB-Chirp3-HD-Kore",
            defaultLanguage: "en",
            defaultAccent: "gb",
            defaultGender: "__all__",
            onChange,
        });
    });
});
