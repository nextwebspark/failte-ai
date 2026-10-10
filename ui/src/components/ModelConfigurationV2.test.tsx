import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ModelConfigurationV2 from "@/components/ModelConfigurationV2";
import { platformCatalogFixture as catalog } from "@/lib/__fixtures__/platformCatalog";

const mocks = vi.hoisted(() => ({
    getDefaults: vi.fn(),
    getConfig: vi.fn(),
    save: vi.fn(),
    permissions: ["credentials:write"] as string[],
    toast: vi.fn(),
}));

vi.mock("@/client/sdk.gen", () => ({
    getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet: mocks.getDefaults,
    getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get: mocks.getConfig,
    saveModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Put: mocks.save,
    getVoicesApiV1UserConfigurationsVoicesProviderGet: vi.fn().mockResolvedValue({
        data: { voices: [], facets: { genders: [], accents: [], languages: [] } },
    }),
}));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ loading: false, user: { id: 1 }, getAccessToken: async () => "token" }),
}));
vi.mock("@/lib/modelConfigurationPricing", () => ({ fetchModelConfigurationPricing: async () => null }));
vi.mock("@/context/UserConfigContext", () => ({ useUserConfig: () => ({ refreshConfig: vi.fn() }) }));
vi.mock("@/context/AppConfigContext", () => ({ useAppConfig: () => ({ config: { platformModelsEnabled: true } }) }));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: (...required: string[]) => required.every((p) => mocks.permissions.includes(p)) }),
}));
vi.mock("sonner", () => ({ toast: { success: mocks.toast } }));
vi.mock("@/components/AIModelConfigurationV2Editor", () => ({
    AIModelConfigurationV2Editor: () => <div>Legacy editor</div>,
    legacyModelConfigurationDefaults: (defaults: { dograh?: unknown; byok?: unknown }) =>
        defaults?.dograh && defaults?.byok ? defaults : null,
}));

const DOGRAH_CONFIG = { version: 2, mode: "dograh", dograh: {} };

function response(configuration: unknown) {
    return { data: { configuration, effective_configuration: {}, source: "organization_v2" } };
}

beforeEach(() => {
    mocks.permissions = ["credentials:write"];
    mocks.getDefaults.mockResolvedValue({ data: { platform: catalog, dograh: null, byok: null } });
    mocks.getConfig.mockResolvedValue(response(DOGRAH_CONFIG));
    mocks.save.mockImplementation(async ({ body }) => response(body));
    mocks.toast.mockClear();
});

describe("Models & voice page", () => {
    it("moves a workspace onto platform models", async () => {
        render(<ModelConfigurationV2 />);

        expect(await screen.findByText("Models & voice")).toBeTruthy();
        expect(screen.getByText(/default managed setup/)).toBeTruthy();
        // Only the reassurance "no API keys needed" may mention keys.
        expect(screen.queryAllByText(/API key/)).toHaveLength(1);
        expect(screen.queryByText(/BYOK|Managed models|Dograh/)).toBeNull();

        fireEvent.click(screen.getByRole("radio", { name: /Speech-to-Text/ }));
        fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.3" } });
        fireEvent.click(screen.getByRole("button", { name: "Save Configuration" }));

        await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce());
        const body = mocks.save.mock.calls[0][0].body;
        expect(body).toMatchObject({ version: 2, mode: "platform", platform: { pipeline_mode: "pipeline" } });
        expect(body.platform.pipeline.llm.temperature).toBe(0.3);
        await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("Model settings saved"));
        expect(screen.queryByText(/default managed setup/)).toBeNull();
    });

    it("is read-only without permission to change model settings", async () => {
        mocks.permissions = [];
        render(<ModelConfigurationV2 />);

        expect(await screen.findByText("Models & voice")).toBeTruthy();
        expect(screen.queryByRole("button", { name: "Save Configuration" })).toBeNull();
    });

    it("keeps the provider editor when platform models are off", async () => {
        mocks.getDefaults.mockResolvedValue({
            data: { platform: { ...catalog, enabled: false }, dograh: {}, byok: {} },
        });
        render(<ModelConfigurationV2 />);

        expect(await screen.findByText("Legacy editor")).toBeTruthy();
        expect(screen.getByText("AI Models Configuration")).toBeTruthy();
    });
});
