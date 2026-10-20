import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PhoneNumberResponse, TelephonyConfigurationListItem } from "@/client/types.gen";

const mocks = vi.hoisted(() => ({
    listConfigs: vi.fn(),
    listNumbers: vi.fn(),
    update: vi.fn(),
    can: vi.fn(() => true),
    toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock("@/client/sdk.gen", () => ({
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet: mocks.listConfigs,
    listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet: mocks.listNumbers,
    updatePhoneNumberApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersPhoneNumberIdPut: mocks.update,
}));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1" }, loading: false, getAccessToken: async () => "token" }),
}));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ can: mocks.can, orgContext: {} }) }));
vi.mock("sonner", () => ({ toast: mocks.toast }));

import { AgentPhoneNumbers, numberAvailability } from "./AgentPhoneNumbers";

function provider(overrides: Partial<TelephonyConfigurationListItem> = {}): TelephonyConfigurationListItem {
    return { id: 1, name: "Twilio", provider: "twilio", inactive: false, phone_number_count: 1, ...overrides } as TelephonyConfigurationListItem;
}

function number(overrides: Partial<PhoneNumberResponse> = {}): PhoneNumberResponse {
    return {
        id: 10,
        telephony_configuration_id: 1,
        address: "+35315550100",
        label: "Main line",
        inbound_workflow_id: null,
        inbound_workflow_name: null,
        is_active: true,
        ...overrides,
    } as PhoneNumberResponse;
}

function serve(configs: TelephonyConfigurationListItem[], numbers: PhoneNumberResponse[]) {
    mocks.listConfigs.mockResolvedValue({ data: { configurations: configs } });
    mocks.listNumbers.mockResolvedValue({ data: { phone_numbers: numbers } });
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockReturnValue(true);
    mocks.update.mockResolvedValue({ data: { provider_sync: { ok: true } } });
});

describe("numberAvailability", () => {
    const item = (n: Partial<PhoneNumberResponse>, p: Partial<TelephonyConfigurationListItem> = {}) => ({
        number: number(n),
        provider: provider(p),
    });

    it("offers free numbers and numbers another agent answers", () => {
        expect(numberAvailability(item({}), 7)).toEqual({ selectable: true, note: "Not answered by any agent" });
        expect(numberAvailability(item({ inbound_workflow_id: 3, inbound_workflow_name: "Sales" }), 7)).toEqual({
            selectable: true,
            note: "Now answered by Sales",
        });
    });

    it("holds back numbers that can't take calls", () => {
        expect(numberAvailability(item({ is_active: false }), 7).selectable).toBe(false);
        expect(numberAvailability(item({}, { inactive: true }), 7)).toEqual({
            selectable: false,
            note: "Twilio is turned off",
        });
    });
});

describe("AgentPhoneNumbers", () => {
    it("explains what to do when the workspace has no phone provider", async () => {
        serve([], []);
        render(<AgentPhoneNumbers agentId={7} agentName="Harbour Vets reception" />);
        expect(await screen.findByText("Your workspace has no phone numbers yet")).toBeTruthy();
        expect(screen.getByRole("link", { name: /Set up phone numbers/ }).getAttribute("href")).toBe(
            "/telephony-configurations",
        );
    });

    it("connects a number to this agent in one step", async () => {
        serve([provider()], [number({ inbound_workflow_id: 3, inbound_workflow_name: "Sales" })]);
        render(<AgentPhoneNumbers agentId={7} agentName="Harbour Vets reception" />);
        expect(await screen.findByText("This agent doesn’t answer a phone number yet.")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Connect a phone number/ }));
        fireEvent.click(screen.getByRole("radio", { name: /\+35315550100/ }));
        expect(screen.getByText(/Sales will stop answering/)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Connect" }));

        await waitFor(() =>
            expect(mocks.update).toHaveBeenCalledWith(
                expect.objectContaining({
                    path: { config_id: 1, phone_number_id: 10 },
                    body: { inbound_workflow_id: 7 },
                }),
            ),
        );
        expect(mocks.toast.success).toHaveBeenCalledWith("Calls to +35315550100 now go to Harbour Vets reception");
    });

    it("lists the numbers that ring this agent and disconnects one", async () => {
        serve([provider()], [number({ inbound_workflow_id: 7, inbound_workflow_name: "Harbour Vets reception" })]);
        render(<AgentPhoneNumbers agentId={7} agentName="Harbour Vets reception" />);
        expect(await screen.findByText("+35315550100")).toBeTruthy();
        // Nothing else to connect, so only "Add a new number" is offered.
        expect(screen.queryByRole("button", { name: /Connect a phone number/ })).toBeNull();

        fireEvent.click(screen.getByRole("button", { name: /Disconnect/ }));
        await waitFor(() =>
            expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({ body: { clear_inbound_workflow: true } })),
        );
    });

    it("asks people without telephony access to get an admin", () => {
        mocks.can.mockReturnValue(false);
        render(<AgentPhoneNumbers agentId={7} agentName="Harbour Vets reception" />);
        expect(screen.getByText(/Ask a workspace admin/)).toBeTruthy();
        expect(mocks.listConfigs).not.toHaveBeenCalled();
    });
});
