import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";

import IntegrationsPage from "./page";
import { rememberReconnect } from "./reconnect";

const mocks = vi.hoisted(() => ({
    getCatalog: vi.fn(),
    listConnections: vi.fn(),
    listProviderApps: vi.fn(),
    activate: vi.fn(),
    startOauth: vi.fn(),
    createProviderApp: vi.fn(),
    install: vi.fn(),
    update: vi.fn(),
    test: vi.fn(),
    uninstall: vi.fn(),
    can: vi.fn<(...permissions: string[]) => boolean>(() => true),
}));

vi.stubGlobal(
    "ResizeObserver",
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

vi.mock("@/client/sdk.gen", () => ({
    getCatalogApiV1IntegrationsCatalogGet: mocks.getCatalog,
    listConnectionsApiV1IntegrationsConnectionsGet: mocks.listConnections,
    listProviderAppsApiV1IntegrationsProviderAppsGet: mocks.listProviderApps,
    activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost: mocks.activate,
    startOauthApiV1IntegrationsOauthStartPost: mocks.startOauth,
    createProviderAppApiV1IntegrationsProviderAppsPost: mocks.createProviderApp,
    installIntegrationApiV1IntegrationsConnectionsPost: mocks.install,
    updateConnectionConfigApiV1IntegrationsConnectionsConnectionIdPatch: mocks.update,
    testConnectionApiV1IntegrationsConnectionsConnectionIdTestPost: mocks.test,
    uninstallIntegrationApiV1IntegrationsConnectionsConnectionIdDelete: mocks.uninstall,
}));

vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1" }, loading: false }),
}));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can }),
}));

vi.mock("sonner", () => ({
    toast: { success: vi.fn(), error: vi.fn() },
}));

const NEW_ID = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";
const OLD_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const REDIRECT_URI = "https://tools.fallcha.test/oauth/google-calendar/callback";

const PROVIDER: IntegrationProvider = {
    id: "google-calendar",
    title: "Google Calendar",
    description: "Check availability and book appointments.",
    icon: "calendar",
    auth_modes: ["oauth2", "service_account"],
    scopes: [],
    tools: [{ name: "book_appointment", description: "Book a slot" }],
    config_schema: {
        type: "object",
        required: ["calendar_id"],
        properties: { calendar_id: { type: "string", title: "Calendar Id" } },
    },
    oauth: {
        scopes: ["https://www.googleapis.com/auth/calendar.events"],
        optional_scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
        redirect_uri: REDIRECT_URI,
    },
};

function connection(overrides: Partial<IntegrationConnectionResponse>): IntegrationConnectionResponse {
    return {
        id: NEW_ID,
        provider: PROVIDER.id,
        auth_mode: "oauth2",
        account_label: "alice@acme.test",
        scopes_granted: [],
        config: { calendar_id: "primary" },
        status: "active",
        created_at: "2026-10-10T00:00:00Z",
        updated_at: "2026-10-10T00:00:00Z",
        credential_uuid: "cred-1",
        tool_uuids: ["tool-1"],
        ...overrides,
    };
}

function setUrl(search: string) {
    window.history.replaceState(null, "", `/integrations${search}`);
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockImplementation(() => true);
    mocks.getCatalog.mockResolvedValue({ data: { providers: [PROVIDER] } });
    mocks.listConnections.mockResolvedValue({ data: { connections: [] } });
    mocks.listProviderApps.mockResolvedValue({ data: { provider_apps: [] } });
    setUrl("");
});

afterEach(() => {
    window.sessionStorage.clear();
});

describe("IntegrationsPage", () => {
    it("lists the catalog and connections", async () => {
        mocks.listConnections.mockResolvedValue({
            data: {
                connections: [
                    connection({
                        status: "error",
                        error_code: "grant_revoked",
                        last_error: "invalid_grant",
                    }),
                ],
            },
        });
        render(<IntegrationsPage />);

        expect(await screen.findByText("book_appointment")).toBeTruthy();
        expect(screen.getByText("Needs attention")).toBeTruthy();
        expect(screen.getByText(/Access was revoked or expired/)).toBeTruthy();
        expect(screen.getByRole("button", { name: /Reconnect/ })).toBeTruthy();
        expect(screen.getByRole("link", { name: /Agent tool/ }).getAttribute("href")).toBe("/tools/tool-1");
    });

    it("shows the unconfigured-server state on integration_unavailable", async () => {
        mocks.getCatalog.mockResolvedValue({
            error: { detail: "not available", code: "integration_unavailable" },
        });
        render(<IntegrationsPage />);
        expect(await screen.findByText("Integrations aren't configured on this server")).toBeTruthy();
        expect(mocks.listConnections).not.toHaveBeenCalled();
    });

    it("hides connect and remove actions from read-only roles", async () => {
        mocks.can.mockImplementation((...permissions: string[]) =>
            permissions.every((p) => p === "integrations:read"),
        );
        mocks.listConnections.mockResolvedValue({ data: { connections: [connection({})] } });
        render(<IntegrationsPage />);

        expect(await screen.findByText("alice@acme.test")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /Connect/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Test/ })).toBeNull();
        expect(screen.getByText(/You can view integrations/)).toBeTruthy();
    });

    it("activates a returning OAuth connection with credentials and cleans the URL", async () => {
        setUrl(`?tab=connected&integration_result=success&connection_id=${NEW_ID}&provider=google-calendar`);
        mocks.activate.mockResolvedValue({ data: connection({}) });
        render(<IntegrationsPage />);

        await waitFor(() => expect(mocks.activate).toHaveBeenCalledTimes(1));
        expect(mocks.activate).toHaveBeenCalledWith({
            path: { connection_id: NEW_ID },
            credentials: "include",
        });
        expect(window.location.search).toBe("?tab=connected");
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Connected as alice@acme.test"));
        // The provider has required config: its settings are offered for review.
        expect(await screen.findByText("Review Google Calendar settings")).toBeTruthy();
        expect((screen.getByLabelText(/Calendar ID/) as HTMLInputElement).value).toBe("primary");
    });

    it("offers to remove the errored connection a reconnect replaced", async () => {
        const schemaFree = { ...PROVIDER, config_schema: null };
        mocks.getCatalog.mockResolvedValue({ data: { providers: [schemaFree] } });
        mocks.listConnections.mockResolvedValue({
            data: { connections: [connection({ id: OLD_ID, status: "error", error_code: "grant_revoked" })] },
        });
        mocks.activate.mockResolvedValue({ data: connection({}) });
        mocks.uninstall.mockResolvedValue({ data: undefined });
        rememberReconnect({ provider: PROVIDER.id, oldConnectionId: OLD_ID });
        setUrl(`?integration_result=success&connection_id=${NEW_ID}&provider=google-calendar`);
        render(<IntegrationsPage />);

        fireEvent.click(await screen.findByRole("button", { name: "Remove old connection" }));
        await waitFor(() =>
            expect(mocks.uninstall).toHaveBeenCalledWith({ path: { connection_id: OLD_ID } }),
        );
    });

    it("explains an OAuth failure from its reason code", async () => {
        setUrl("?integration_result=error&reason=access_denied");
        render(<IntegrationsPage />);

        expect(await screen.findByText(/You cancelled the sign-in/)).toBeTruthy();
        expect(mocks.activate).not.toHaveBeenCalled();
        expect(window.location.search).toBe("");
    });

    it("starts OAuth with credentials and redirects the browser", async () => {
        const assign = vi.fn();
        const original = window.location;
        Object.defineProperty(window, "location", {
            configurable: true,
            value: { ...original, assign, search: "", href: original.href },
        });
        try {
            mocks.listProviderApps.mockResolvedValue({
                data: {
                    provider_apps: [
                        {
                            id: "app-1",
                            provider: PROVIDER.id,
                            client_id: "1234.apps.googleusercontent.com",
                            created_at: "",
                            updated_at: "",
                        },
                    ],
                },
            });
            mocks.startOauth.mockResolvedValue({
                data: {
                    authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=x",
                    redirect_uri: REDIRECT_URI,
                    expires_at: "",
                },
            });
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
            fireEvent.click(await screen.findByLabelText("Read Google Sheets (for order lookup)"));
            fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

            await waitFor(() =>
                expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?state=x"),
            );
            expect(mocks.startOauth).toHaveBeenCalledWith({
                body: {
                    provider: PROVIDER.id,
                    provider_app_id: "app-1",
                    optional_scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
                },
                credentials: "include",
            });
        } finally {
            Object.defineProperty(window, "location", { configurable: true, value: original });
        }
    });

    it("shows the redirect URI when adding an OAuth client", async () => {
        render(<IntegrationsPage />);
        fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
        expect((await screen.findByLabelText("Redirect URI")).textContent).toBe(REDIRECT_URI);
        expect(screen.getByRole("button", { name: "Copy redirect URI" })).toBeTruthy();
    });
});
