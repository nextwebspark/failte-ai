import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlatformModelEditor } from "@/components/platform/PlatformModelEditor";
import { platformCatalogFixture as catalog } from "@/lib/__fixtures__/platformCatalog";

const voicePicker = vi.hoisted(() => ({ props: null as null | Record<string, unknown> }));

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ getAccessToken: async () => "token" }) }));
vi.mock("@/components/platform/PlatformTtsVoicePicker", () => ({
    PlatformTtsVoicePicker: (props: Record<string, unknown>) => {
        voicePicker.props = props;
        return <span data-testid="tts-voice">{String(props.value)}</span>;
    },
}));

const PIPELINE = {
    version: 2,
    mode: "platform",
    platform: {
        pipeline_mode: "pipeline",
        pipeline: {
            llm: { model: "gemini-3.5-flash", temperature: 0.1 },
            stt: { model: "chirp_3", language: "en-US" },
            tts: { model: "chirp_3_hd", voice: "en-US-Chirp3-HD-Kore", language: "en-US", speed: 1 },
        },
    },
};

function renderEditor(configuration: unknown, onSave = vi.fn(), editorCatalog = catalog) {
    render(<PlatformModelEditor catalog={editorCatalog} configuration={configuration} onSave={onSave} />);
    return onSave;
}

const save = () => fireEvent.click(screen.getByRole("button", { name: "Save Configuration" }));

describe("PlatformModelEditor", () => {
    it("saves a speech-to-speech choice without keys or providers", async () => {
        const onSave = renderEditor(null);

        expect(screen.getByRole("radio", { name: /Speech-to-Speech/ }).getAttribute("aria-checked")).toBe("true");
        expect(screen.queryByText(/API key/i)).toBeNull();
        fireEvent.click(screen.getByRole("radio", { name: /Kore/ }));
        save();

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        expect(onSave.mock.calls[0][0]).toEqual({
            version: 2,
            mode: "platform",
            platform: {
                pipeline_mode: "realtime",
                realtime: { model: "google/gemini-live-2.5-flash-native-audio", voice: "Kore", language: "en" },
            },
        });
    });

    it("switches to the pipeline path and saves its choices", async () => {
        const onSave = renderEditor(null);

        fireEvent.click(screen.getByRole("radio", { name: /Speech-to-Text/ }));
        fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.4" } });
        fireEvent.change(screen.getByLabelText("Speed"), { target: { value: "1.2" } });
        save();

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        const platform = onSave.mock.calls[0][0].platform;
        expect(platform.pipeline_mode).toBe("pipeline");
        expect(platform.realtime).toBeUndefined();
        expect(platform.pipeline.llm).toEqual({ model: "gemini-3.5-flash", temperature: 0.4 });
        expect(platform.pipeline.tts.speed).toBe(1.2);
    });

    it("keeps each mode's choices when switching back and forth", async () => {
        const onSave = renderEditor(null);

        fireEvent.click(screen.getByRole("radio", { name: /Kore/ }));
        fireEvent.click(screen.getByRole("radio", { name: /Speech-to-Text/ }));
        expect(screen.getByText("Speech-to-text")).toBeTruthy();
        expect(screen.getByText("Language model")).toBeTruthy();
        expect(screen.getByText("Text-to-speech")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.7" } });
        fireEvent.click(screen.getByRole("radio", { name: /Speech-to-Speech/ }));
        expect(screen.getByRole("radio", { name: /Kore/ }).getAttribute("aria-checked")).toBe("true");
        fireEvent.click(screen.getByRole("radio", { name: /Speech-to-Text/ }));
        expect((screen.getByLabelText("Temperature") as HTMLInputElement).value).toBe("0.7");
        save();

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        expect(onSave.mock.calls[0][0].platform.pipeline.llm.temperature).toBe(0.7);
    });

    it("lets a number field be cleared while typing", () => {
        renderEditor(PIPELINE);
        const speed = screen.getByLabelText("Speed") as HTMLInputElement;

        fireEvent.change(speed, { target: { value: "" } });
        expect(speed.value).toBe("");
        fireEvent.change(speed, { target: { value: "1.5" } });
        expect(speed.value).toBe("1.5");
        fireEvent.change(speed, { target: { value: "" } });
        fireEvent.blur(speed);
        expect(speed.value).toBe("1");
    });

    it("has no key, credential or provider fields", () => {
        renderEditor(PIPELINE);
        for (const label of document.querySelectorAll("label")) {
            expect(label.textContent).not.toMatch(/api.?key|credential|provider|region|project/i);
        }
    });

    it("moves the voice language with a voice picked in another language", async () => {
        const onSave = renderEditor(PIPELINE);

        act(() => (voicePicker.props?.onChange as (voice: string) => void)("en-GB-Chirp3-HD-Aoede"));
        save();

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        expect(onSave.mock.calls[0][0].platform.pipeline.tts).toMatchObject({
            voice: "en-GB-Chirp3-HD-Aoede",
            language: "en-GB",
        });
    });

    it("blocks saving choices the catalog rejects", async () => {
        const invalid = structuredClone(PIPELINE);
        invalid.platform.pipeline.stt = { model: "latest_long", language: "cy-GB" };
        const onSave = renderEditor(invalid);

        save();

        expect(await screen.findByText(/speech-to-text model doesn't support this language/)).toBeTruthy();
        expect(onSave).not.toHaveBeenCalled();
    });

    it("shows a save failure from the server", async () => {
        renderEditor(null, vi.fn().mockRejectedValue(new Error("Platform models are not enabled")));

        save();

        expect(await screen.findByText("Platform models are not enabled")).toBeTruthy();
    });

    it("explains starting from defaults for a workspace on its own keys", () => {
        renderEditor({ version: 2, mode: "byok", byok: {} });
        expect(screen.getByText(/default managed setup/)).toBeTruthy();
    });

    it("is read-only for viewers without permission", () => {
        render(<PlatformModelEditor catalog={catalog} configuration={PIPELINE} onSave={vi.fn()} readOnly />);

        expect(screen.queryByRole("button", { name: "Save Configuration" })).toBeNull();
        expect(screen.queryByText(/managed by Fallcha.ai support/)).toBeNull();
        expect((screen.getByLabelText("Speed") as HTMLInputElement).disabled).toBe(true);
    });

    it("is read-only when support pinned the settings", () => {
        renderEditor(PIPELINE, vi.fn(), { ...catalog, locked: true });

        expect(screen.getByText(/managed by Fallcha.ai support/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: "Save Configuration" })).toBeNull();
        expect((screen.getByLabelText("Temperature") as HTMLInputElement).disabled).toBe(true);
    });
});
