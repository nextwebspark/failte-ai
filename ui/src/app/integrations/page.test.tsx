import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";

import IntegrationsPage from "./page";
import { rememberPendingOAuth } from "./pendingOAuth";

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
    role: "developer" as string | null,
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
    useOrgConfig: () => ({ can: mocks.can, role: mocks.role, loading: false }),
}));

vi.mock("sonner", () => ({
    toast: { success: vi.fn(), error: vi.fn() },
}));

const NEW_ID = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";
const OLD_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const NONCE = "nonce-from-oauth-start";
const REDIRECT_URI = "https://tools.fallcha.test/oauth/google-calendar/callback";
const AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth?state=x";
const SUCCESS_QUERY = `?integration_result=success&connection_id=${NEW_ID}&provider=google-calendar`;

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

const APP = {
    id: "app-1",
    provider: PROVIDER.id,
    client_id: "1234.apps.googleusercontent.com",
    created_at: "",
    updated_at: "",
};

const SA_KEY = JSON.stringify({
    type: "service_account",
    client_email: "booking@acme.iam.gserviceaccount.com",
    private_key: "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
});

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

function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => {
        resolve = r;
    });
    return { promise, resolve };
}

/** Radix tabs switch on mouse down. */
function chooseTab(name: RegExp) {
    fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockImplementation(() => true);
    mocks.role = "developer";
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
                connections: [connection({ status: "error", error_code: "grant_revoked", last_error: "invalid_grant" })],
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
        mocks.getCatalog.mockResolvedValue({ error: { detail: "not available", code: "integration_unavailable" } });
        render(<IntegrationsPage />);
        expect(await screen.findByText("Integrations aren't configured on this server")).toBeTruthy();
        expect(mocks.listConnections).not.toHaveBeenCalled();
    });

    it("shows no access and fetches nothing without integrations:read", async () => {
        mocks.role = "viewer";
        mocks.can.mockImplementation(() => false);
        render(<IntegrationsPage />);
        expect(await screen.findByText("You don't have access to this page")).toBeTruthy();
        expect(mocks.getCatalog).not.toHaveBeenCalled();
        expect(mocks.listConnections).not.toHaveBeenCalled();
    });

    it("hides write actions and the tool link from read-only roles", async () => {
        mocks.can.mockImplementation((...permissions: string[]) => permissions.every((p) => p === "integrations:read"));
        mocks.listConnections.mockResolvedValue({ data: { connections: [connection({})] } });
        render(<IntegrationsPage />);

        expect(await screen.findByText("alice@acme.test")).toBeTruthy();
        for (const name of [/Connect/, /Remove/, /Test/, /Settings/]) {
            expect(screen.queryByRole("button", { name })).toBeNull();
        }
        expect(screen.queryByRole("link", { name: /Agent tool/ })).toBeNull();
        expect(screen.getByText(/You can view integrations/)).toBeTruthy();
    });

    it("toasts a failed refresh after the first load instead of replacing the page", async () => {
        mocks.listConnections
            .mockResolvedValueOnce({ data: { connections: [connection({})] } })
            .mockResolvedValueOnce({ error: { detail: "boom" } });
        mocks.uninstall.mockResolvedValue({ data: undefined });
        render(<IntegrationsPage />);

        fireEvent.click(await screen.findByRole("button", { name: /Remove/ }));
        fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("boom"));
        expect(screen.getByText("alice@acme.test")).toBeTruthy();
        expect(screen.getByText("Available integrations")).toBeTruthy();
    });

    describe("OAuth return", () => {
        it("activates after the first load with the stored nonce, then refreshes", async () => {
            const firstList = deferred<{ data: { connections: IntegrationConnectionResponse[] } }>();
            mocks.listConnections
                .mockReturnValueOnce(firstList.promise)
                .mockResolvedValue({ data: { connections: [connection({})] } });
            mocks.activate.mockResolvedValue({ data: connection({}) });
            rememberPendingOAuth(PROVIDER.id, { nonce: NONCE });
            setUrl(`?tab=connected&${SUCCESS_QUERY.slice(1)}`);
            render(<IntegrationsPage />);

            await waitFor(() => expect(mocks.listConnections).toHaveBeenCalledTimes(1));
            expect(mocks.activate).not.toHaveBeenCalled();
            // The stale initial list (without the new connection) lands first.
            firstList.resolve({ data: { connections: [] } });

            await waitFor(() => expect(mocks.activate).toHaveBeenCalledTimes(1));
            expect(mocks.activate).toHaveBeenCalledWith({
                path: { connection_id: NEW_ID },
                body: { browser_nonce: NONCE },
            });
            await waitFor(() => expect(mocks.listConnections).toHaveBeenCalledTimes(2));
            expect(window.location.search).toBe("?tab=connected");
            expect(window.sessionStorage.length).toBe(0);
            expect(toast.success).toHaveBeenCalledWith("Connected as alice@acme.test");
            // Required config: the settings are offered for review.
            expect(await screen.findByText("Review Google Calendar settings")).toBeTruthy();
            expect((screen.getByLabelText(/Calendar ID/) as HTMLInputElement).value).toBe("primary");
            expect(screen.getAllByText("alice@acme.test").length).toBeGreaterThan(0);
        });

        it("activates once under StrictMode", async () => {
            mocks.activate.mockResolvedValue({ data: connection({}) });
            rememberPendingOAuth(PROVIDER.id, { nonce: NONCE });
            setUrl(SUCCESS_QUERY);
            render(
                <StrictMode>
                    <IntegrationsPage />
                </StrictMode>,
            );
            await waitFor(() => expect(toast.success).toHaveBeenCalled());
            expect(mocks.activate).toHaveBeenCalledTimes(1);
        });

        it("refuses to activate without a stored nonce", async () => {
            setUrl(SUCCESS_QUERY);
            render(<IntegrationsPage />);
            expect(await screen.findByText(/can't be confirmed here/)).toBeTruthy();
            expect(mocks.activate).not.toHaveBeenCalled();
        });

        it("offers to remove the errored connection a reconnect replaced", async () => {
            mocks.getCatalog.mockResolvedValue({ data: { providers: [{ ...PROVIDER, config_schema: null }] } });
            mocks.listConnections.mockResolvedValue({
                data: { connections: [connection({ id: OLD_ID, status: "error", error_code: "grant_revoked" })] },
            });
            mocks.activate.mockResolvedValue({ data: connection({}) });
            mocks.uninstall.mockResolvedValue({ data: undefined });
            rememberPendingOAuth(PROVIDER.id, { nonce: NONCE, replacesConnectionId: OLD_ID });
            setUrl(SUCCESS_QUERY);
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: "Remove old connection" }));
            await waitFor(() => expect(mocks.uninstall).toHaveBeenCalledWith({ path: { connection_id: OLD_ID } }));
        });

        it("toasts when removing the replaced connection fails", async () => {
            mocks.getCatalog.mockResolvedValue({ data: { providers: [{ ...PROVIDER, config_schema: null }] } });
            mocks.listConnections.mockResolvedValue({
                data: { connections: [connection({ id: OLD_ID, status: "error", error_code: "grant_revoked" })] },
            });
            mocks.activate.mockResolvedValue({ data: connection({}) });
            mocks.uninstall.mockRejectedValue(new TypeError("Failed to fetch"));
            rememberPendingOAuth(PROVIDER.id, { nonce: NONCE, replacesConnectionId: OLD_ID });
            setUrl(SUCCESS_QUERY);
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: "Remove old connection" }));
            await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't reach the server. Please try again."));
        });

        it("explains an OAuth failure from its reason code and forgets the nonce", async () => {
            rememberPendingOAuth(PROVIDER.id, { nonce: NONCE });
            setUrl("?integration_result=error&reason=access_denied");
            render(<IntegrationsPage />);

            expect(await screen.findByText(/You cancelled the sign-in/)).toBeTruthy();
            expect(mocks.activate).not.toHaveBeenCalled();
            expect(window.location.search).toBe("");
            expect(window.sessionStorage.length).toBe(0);
        });
    });

    describe("connect flows", () => {
        const original = window.location;
        let assign: ReturnType<typeof vi.fn>;

        beforeEach(() => {
            assign = vi.fn();
            Object.defineProperty(window, "location", {
                configurable: true,
                value: { ...original, assign, search: "", href: original.href },
            });
        });

        afterEach(() => {
            Object.defineProperty(window, "location", { configurable: true, value: original });
        });

        it("starts OAuth, stores the nonce and redirects the browser", async () => {
            mocks.listProviderApps.mockResolvedValue({ data: { provider_apps: [APP] } });
            mocks.startOauth.mockResolvedValue({
                data: { authorization_url: AUTHORIZE_URL, redirect_uri: REDIRECT_URI, expires_at: "", browser_nonce: NONCE },
            });
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
            fireEvent.click(await screen.findByLabelText("Read Google Sheets (for order lookup)"));
            fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

            await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTHORIZE_URL));
            expect(mocks.startOauth).toHaveBeenCalledWith({
                body: {
                    provider: PROVIDER.id,
                    provider_app_id: "app-1",
                    optional_scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
                },
            });
            const stored = JSON.parse(window.sessionStorage.getItem("fallcha.integrations.oauth.google-calendar") ?? "{}");
            expect(stored.nonce).toBe(NONCE);
        });

        it.each(["http://accounts.google.com/auth", "https://evil.example/auth", "https://accounts.google.com.evil.example/x", "javascript:alert(1)"])(
            "refuses to redirect to %s",
            async (url) => {
                mocks.listProviderApps.mockResolvedValue({ data: { provider_apps: [APP] } });
                mocks.startOauth.mockResolvedValue({
                    data: { authorization_url: url, redirect_uri: REDIRECT_URI, expires_at: "", browser_nonce: NONCE },
                });
                render(<IntegrationsPage />);

                fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
                fireEvent.click(await screen.findByRole("button", { name: "Sign in" }));

                expect(await screen.findByText(/unexpected sign-in address/)).toBeTruthy();
                expect(assign).not.toHaveBeenCalled();
                expect(window.sessionStorage.length).toBe(0);
            },
        );

        it("uses a newly saved OAuth client straight away", async () => {
            mocks.createProviderApp.mockResolvedValue({ data: APP });
            mocks.startOauth.mockResolvedValue({ error: { detail: "Google said no", code: "integration_invalid_request" } });
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
            expect((await screen.findByLabelText("Redirect URI")).textContent).toBe(REDIRECT_URI);
            expect(screen.getByRole("button", { name: "Copy redirect URI" })).toBeTruthy();
            fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: APP.client_id } });
            fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "shh" } });
            fireEvent.click(screen.getByRole("button", { name: "Save and sign in" }));

            expect(await screen.findByText("Google said no")).toBeTruthy();
            // The saved client is now selectable without a reload, and is selected.
            expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
            expect(screen.queryByLabelText("Client secret")).toBeNull();
            expect(mocks.listProviderApps).toHaveBeenCalledTimes(1);
        });

        it("installs with a service account key and clears it afterwards", async () => {
            mocks.install.mockResolvedValue({
                data: connection({ auth_mode: "service_account", account_label: "booking@acme.iam.gserviceaccount.com" }),
            });
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
            chooseTab(/Service account key/);
            fireEvent.change(await screen.findByLabelText("Service account key (JSON)"), { target: { value: SA_KEY } });
            fireEvent.change(screen.getByLabelText(/Calendar ID/), { target: { value: "team@group.calendar.google.com" } });
            fireEvent.click(screen.getByRole("button", { name: "Connect" }));

            await waitFor(() => expect(mocks.install).toHaveBeenCalledTimes(1));
            expect(mocks.install.mock.calls[0][0].body).toMatchObject({
                provider: PROVIDER.id,
                auth_mode: "service_account",
                account_label: "booking@acme.iam.gserviceaccount.com",
                config: { calendar_id: "team@group.calendar.google.com" },
                secret: JSON.parse(SA_KEY),
            });
            await waitFor(() => expect(screen.queryByLabelText("Service account key (JSON)")).toBeNull());

            fireEvent.click(screen.getByRole("button", { name: /Add another/ }));
            chooseTab(/Service account key/);
            expect(((await screen.findByLabelText("Service account key (JSON)")) as HTMLTextAreaElement).value).toBe("");
        });

        it("shows one error for an oversized key file", async () => {
            render(<IntegrationsPage />);
            fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
            chooseTab(/Service account key/);
            const input = document.querySelector<HTMLInputElement>('input[type="file"]');
            const big = new File(["x".repeat(70 * 1024)], "huge.json", { type: "application/json" });
            fireEvent.change(input as HTMLInputElement, { target: { files: [big] } });

            expect(await screen.findByText("That file is too large to be a key.")).toBeTruthy();
            expect(screen.getAllByRole("alert")).toHaveLength(1);
        });
    });

    describe("settings", () => {
        it("saves settings and shows validation errors from the server", async () => {
            mocks.listConnections.mockResolvedValue({ data: { connections: [connection({})] } });
            mocks.update
                .mockResolvedValueOnce({
                    error: { detail: [{ loc: ["body", "config"], msg: "invalid config: unknown calendar", type: "value_error" }] },
                })
                .mockResolvedValueOnce({ data: connection({ config: { calendar_id: "team" } }) });
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: /Settings/ }));
            const field = await screen.findByLabelText(/Calendar ID/);
            fireEvent.change(field, { target: { value: "team" } });
            fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

            expect(await screen.findByText("invalid config: unknown calendar")).toBeTruthy();
            expect(mocks.update).toHaveBeenCalledWith({
                path: { connection_id: NEW_ID },
                body: { config: { calendar_id: "team" } },
            });

            fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
            await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Settings saved"));
            await waitFor(() => expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull());
        });

        it("blocks saving when a required field is empty", async () => {
            mocks.listConnections.mockResolvedValue({ data: { connections: [connection({})] } });
            render(<IntegrationsPage />);

            fireEvent.click(await screen.findByRole("button", { name: /Settings/ }));
            fireEvent.change(await screen.findByLabelText(/Calendar ID/), { target: { value: " " } });
            fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

            expect(await screen.findByText("Required")).toBeTruthy();
            expect(mocks.update).not.toHaveBeenCalled();
        });
    });
});
