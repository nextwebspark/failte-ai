import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";

import IntegrationsPage from "./page";

const mocks = vi.hoisted(() => ({
    getCatalog: vi.fn(),
    listConnections: vi.fn(),
    listProviderApps: vi.fn(),
    install: vi.fn(),
    update: vi.fn(),
    choices: vi.fn(),
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
    installIntegrationApiV1IntegrationsConnectionsPost: mocks.install,
    updateConnectionConfigApiV1IntegrationsConnectionsConnectionIdPatch: mocks.update,
    listConnectionChoicesApiV1IntegrationsConnectionsConnectionIdChoicesGet: mocks.choices,
    activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost: vi.fn(),
    startOauthApiV1IntegrationsOauthStartPost: vi.fn(),
    createProviderAppApiV1IntegrationsProviderAppsPost: vi.fn(),
    testConnectionApiV1IntegrationsConnectionsConnectionIdTestPost: vi.fn(),
    uninstallIntegrationApiV1IntegrationsConnectionsConnectionIdDelete: vi.fn(),
    syncConnectionApiV1IntegrationsConnectionsConnectionIdSyncPost: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: "1" }, loading: false }) }));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, role: "admin", loading: false }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ID = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";
const TOKEN = "eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0";
const EVENT = "https://api.calendly.com/event_types/ET-1";

const CALENDLY: IntegrationProvider = {
    id: "calendly",
    title: "Calendly",
    description: "Offer free times from one of your Calendly events and book callers into it.",
    icon: "calendar",
    auth_modes: ["api_key", "oauth2"],
    scopes: ["users:read", "event_types:read", "availability:read", "scheduled_events:write"],
    tools: [
        { name: "check_appointment_availability", description: "", summary: "Check free times in Calendly" },
        { name: "book_appointment", description: "", summary: "Book in Calendly" },
    ],
    capabilities: ["bookings", "choices"],
    config_schema: {
        type: "object",
        properties: {
            event_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, "x-fallcha-choice": "value" },
            event_type_name: {
                anyOf: [{ type: "string" }, { type: "null" }],
                default: null,
                "x-fallcha-choice": "label",
            },
            ai_booking_enabled: { type: "boolean", default: true },
        },
    },
    oauth: {
        scopes: ["users:read", "event_types:read", "availability:read", "scheduled_events:write"],
        optional_scopes: [],
        redirect_uri: "https://tools.example/oauth/calendly/callback",
    },
};

function connection(config: Record<string, unknown>): IntegrationConnectionResponse {
    return {
        id: ID,
        provider: "calendly",
        auth_mode: "api_key",
        account_label: "aoife@example.ie",
        scopes_granted: [],
        config,
        status: "active",
        created_at: "2026-11-06T00:00:00Z",
        updated_at: "2026-11-06T00:00:00Z",
        credential_uuid: "cred-1",
        tool_uuids: ["tool-1"],
    };
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockImplementation(() => true);
    mocks.getCatalog.mockResolvedValue({ data: { providers: [CALENDLY] } });
    mocks.listConnections.mockResolvedValue({ data: { connections: [] } });
    mocks.listProviderApps.mockResolvedValue({ data: { provider_apps: [] } });
    mocks.choices.mockResolvedValue({
        data: {
            field: "event_type",
            choices: [
                {
                    value: EVENT,
                    label: "Consultation",
                    detail: "30 minutes",
                    config: { event_type: EVENT, event_type_name: "Consultation" },
                },
                {
                    value: "https://api.calendly.com/event_types/ET-2",
                    label: "Site visit",
                    detail: "1 hour",
                    warning: "Your agent can't book this one.",
                    config: { event_type: "https://api.calendly.com/event_types/ET-2", event_type_name: "Site visit" },
                },
            ],
        },
    });
});

afterEach(() => {
    window.sessionStorage.clear();
});

describe("Connecting Calendly", () => {
    it("pastes a token, then picks the event callers book", async () => {
        mocks.install.mockResolvedValue({ data: connection({ event_type: null }) });
        mocks.update.mockResolvedValue({ data: connection({ event_type: EVENT, event_type_name: "Consultation" }) });
        render(<IntegrationsPage />);

        fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
        // No ready-made sign-in: the token comes first.
        expect(screen.getByRole("tab", { name: "Personal access token" }).getAttribute("aria-selected")).toBe("true");
        expect(screen.getByText(/never says a caller is booked unless Calendly confirmed it/)).toBeTruthy();
        const input = screen.getByLabelText("Personal access token");
        fireEvent.click(screen.getByRole("button", { name: "Connect" }));
        expect(await screen.findByText("Paste your token.")).toBeTruthy();
        expect(mocks.install).not.toHaveBeenCalled();

        fireEvent.change(input, { target: { value: `  ${TOKEN}  ` } });
        fireEvent.click(screen.getByRole("button", { name: "Connect" }));
        await waitFor(() => expect(mocks.install).toHaveBeenCalledTimes(1));
        expect(mocks.install.mock.calls[0][0].body).toEqual({
            provider: "calendly",
            auth_mode: "api_key",
            secret: { token: TOKEN },
        });

        expect(await screen.findByText("Which Calendly event should callers book?")).toBeTruthy();
        expect(await screen.findByText("Your agent can't book this one.")).toBeTruthy();
        expect(mocks.choices).toHaveBeenCalledWith({ path: { connection_id: ID } });
        fireEvent.click(screen.getByRole("radio", { name: /Consultation/ }));
        fireEvent.click(screen.getByRole("button", { name: "Save" }));

        await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
        expect(mocks.update.mock.calls[0][0]).toEqual({
            path: { connection_id: ID },
            body: { config: { event_type: EVENT, event_type_name: "Consultation" } },
        });
        expect(toast.success).toHaveBeenCalledWith("Callers now book “Consultation”");
        expect(await screen.findByText("Consultation")).toBeTruthy();
        expect(screen.getByRole("button", { name: /Change event/ })).toBeTruthy();
    });

    it("shows Calendly's refusal of a token in its own words", async () => {
        mocks.install.mockResolvedValue({
            error: { detail: "Calendly didn't accept this token. Copy it again from Calendly." },
        });
        render(<IntegrationsPage />);
        fireEvent.click(await screen.findByRole("button", { name: /^Connect$/ }));
        fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: TOKEN } });
        fireEvent.click(screen.getByRole("button", { name: "Connect" }));
        expect(await screen.findByText(/didn't accept this token/)).toBeTruthy();
        expect(screen.queryByText("Which Calendly event should callers book?")).toBeNull();
    });

    it("says when no event is chosen yet, and offers to choose one", async () => {
        mocks.listConnections.mockResolvedValue({ data: { connections: [connection({ event_type: null })] } });
        render(<IntegrationsPage />);
        expect(await screen.findByText(/Choose which Calendly event callers book/)).toBeTruthy();
        expect(screen.getByText(/· Personal access token/)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /Choose event/ }));
        expect(await screen.findByText("Which Calendly event should callers book?")).toBeTruthy();
    });

    it("explains when Calendly can't be read", async () => {
        mocks.listConnections.mockResolvedValue({ data: { connections: [connection({ event_type: null })] } });
        mocks.choices.mockResolvedValue({ error: { detail: "Calendly is having problems; please try again shortly" } });
        render(<IntegrationsPage />);
        fireEvent.click(await screen.findByRole("button", { name: /Choose event/ }));
        expect(await screen.findByText(/Calendly is having problems/)).toBeTruthy();
        expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
    });
});
