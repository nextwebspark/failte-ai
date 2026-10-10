import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { platformCatalogFixture as catalog } from "@/lib/__fixtures__/platformCatalog";
import type { WorkflowConfigurations } from "@/types/workflow-configurations";

import { WorkflowModelOverridesSection } from "./WorkflowModelOverridesSection";

const mocks = vi.hoisted(() => ({ getDefaults: vi.fn(), getConfig: vi.fn() }));

vi.mock("@/client/sdk.gen", () => ({
    getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet: mocks.getDefaults,
    getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get: mocks.getConfig,
    getVoicesApiV1UserConfigurationsVoicesProviderGet: vi.fn().mockResolvedValue({
        data: { voices: [], facets: { genders: [], accents: [], languages: [] } },
    }),
}));
vi.mock("@/lib/modelConfigurationPricing", () => ({ fetchModelConfigurationPricing: async () => null }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ getAccessToken: async () => "token" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ can: () => true }) }));
vi.mock("@/components/AIModelConfigurationV2Editor", () => ({
    AIModelConfigurationV2Editor: () => <div>Legacy editor</div>,
    legacyModelConfigurationDefaults: (defaults: { dograh?: unknown; byok?: unknown }) =>
        defaults?.dograh && defaults?.byok ? defaults : null,
}));

const WORKSPACE = {
    version: 2,
    mode: "platform",
    platform: {
        pipeline_mode: "realtime",
        realtime: { model: "google/gemini-live-2.5-flash-native-audio", voice: "Charon", language: "en" },
    },
};

beforeEach(() => {
    mocks.getDefaults.mockResolvedValue({ data: { platform: catalog, dograh: null, byok: null } });
    mocks.getConfig.mockResolvedValue({
        data: { configuration: WORKSPACE, effective_configuration: {}, source: "organization_v2" },
    });
});

function renderSection(workflowConfigurations: Record<string, unknown>, onSave = vi.fn().mockResolvedValue(undefined)) {
    render(
        <WorkflowModelOverridesSection
            // Only the model keys matter here.
            workflowConfigurations={workflowConfigurations as unknown as WorkflowConfigurations}
            workflowName="Agent A"
            onSave={onSave}
        />,
    );
    return onSave;
}

describe("Agent model and voice", () => {
    it("summarises the workspace default when the agent has no override", async () => {
        renderSection({});

        expect(
            await screen.findByText("Speech-to-Speech · Gemini Live 2.5 Flash · Charon · English"),
        ).toBeTruthy();
        expect(screen.queryByText(/API key|BYOK/)).toBeNull();
    });

    it("saves a full platform override for this agent only", async () => {
        const onSave = renderSection({ max_call_duration: 600, model_overrides: { llm: { model: "x" } } });

        fireEvent.click(await screen.findByLabelText("Use a different voice or model for this agent"));
        fireEvent.click(screen.getByRole("radio", { name: /Kore/ }));
        fireEvent.click(screen.getByRole("button", { name: "Save agent voice & model" }));

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        const [saved, name] = onSave.mock.calls[0];
        expect(name).toBe("Agent A");
        expect(saved.max_call_duration).toBe(600);
        expect(saved.model_overrides).toBeUndefined();
        expect(saved.model_configuration_v2_override.platform.realtime.voice).toBe("Kore");
    });

    it("opens an existing platform override and can return to the default", async () => {
        const override = structuredClone(WORKSPACE);
        override.platform.realtime.voice = "Kore";
        const onSave = renderSection({ model_configuration_v2_override: override });

        const kore = await screen.findByRole("radio", { name: /Kore/ });
        expect(kore.getAttribute("aria-checked")).toBe("true");

        fireEvent.click(screen.getByLabelText("Use a different voice or model for this agent"));
        fireEvent.click(screen.getByRole("button", { name: "Use workspace default" }));

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        expect(onSave.mock.calls[0][0].model_configuration_v2_override).toBeUndefined();
    });

    it("lets a pinned workspace drop an agent override but not add one", async () => {
        mocks.getDefaults.mockResolvedValue({ data: { platform: { ...catalog, locked: true }, dograh: null, byok: null } });
        const onSave = renderSection({ model_configuration_v2_override: WORKSPACE });

        fireEvent.click(await screen.findByRole("button", { name: "Use workspace default" }));

        await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
        expect(onSave.mock.calls[0][0].model_configuration_v2_override).toBeUndefined();
    });

    it("treats an old provider override as none", async () => {
        renderSection({ model_configuration_v2_override: { version: 2, mode: "byok", byok: {} } });

        const toggle = await screen.findByLabelText("Use a different voice or model for this agent");
        expect(toggle.getAttribute("aria-checked")).toBe("false");
        expect(screen.getByRole("button", { name: "Use workspace default" })).toBeTruthy();
    });

    it("shows a failed save", async () => {
        renderSection({}, vi.fn().mockRejectedValue(new Error("Model settings are pinned")));

        fireEvent.click(await screen.findByLabelText("Use a different voice or model for this agent"));
        fireEvent.click(screen.getByRole("button", { name: "Save agent voice & model" }));

        expect(await screen.findByText("Model settings are pinned")).toBeTruthy();
    });

    it("keeps the provider editor when platform models are off", async () => {
        mocks.getDefaults.mockResolvedValue({
            data: { platform: { ...catalog, enabled: false }, dograh: {}, byok: {} },
        });
        renderSection({ model_configuration_v2_override: WORKSPACE });

        expect(await screen.findByText("Legacy editor")).toBeTruthy();
    });
});
