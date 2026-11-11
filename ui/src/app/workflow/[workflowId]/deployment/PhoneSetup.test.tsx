import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentPhoneNumber, PhoneSetupResponse } from "@/client/types.gen";

const mocks = vi.hoisted(() => ({
    getSetup: vi.fn(),
    putSetup: vi.fn(),
    search: vi.fn(),
    buy: vi.fn(),
    copy: vi.fn(async () => undefined),
    can: vi.fn(() => true),
    toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock("@/client/sdk.gen", () => ({
    getPhoneSetupApiV1WorkflowWorkflowIdPhoneSetupGet: mocks.getSetup,
    updatePhoneSetupApiV1WorkflowWorkflowIdPhoneSetupPut: mocks.putSetup,
    listAvailablePlatformNumbersApiV1PlatformNumbersAvailableGet: mocks.search,
    getPlatformNumberApiV1WorkflowWorkflowIdPlatformNumberPost: mocks.buy,
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet: vi.fn(async () => ({
        data: { configurations: [] },
    })),
    listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet: vi.fn(),
    updatePhoneNumberApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersPhoneNumberIdPut: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1" }, loading: false, getAccessToken: async () => "token" }),
}));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ can: mocks.can, orgContext: {} }) }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("sonner", () => ({ toast: mocks.toast }));

import { PhoneSetup, primaryNumber } from "./PhoneSetup";

function agentNumber(overrides: Partial<AgentPhoneNumber> = {}): AgentPhoneNumber {
    return {
        id: 10,
        telephony_configuration_id: 3,
        address: "+35315550142",
        address_normalized: "+35315550142",
        label: null,
        provider: "twilio",
        provider_name: "LightMove numbers",
        is_active: true,
        provider_inactive: false,
        lightmove_number: true,
        setup: null,
        check: { status: "not_started" },
        ...overrides,
    } as AgentPhoneNumber;
}

function setup(numbers: AgentPhoneNumber[], available = true): PhoneSetupResponse {
    return { platform_numbers_available: available, numbers };
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockReturnValue(true);
});

describe("primaryNumber", () => {
    it("prefers a number that can take calls", () => {
        const off = agentNumber({ id: 1, is_active: false });
        const on = agentNumber({ id: 2 });
        expect(primaryNumber([off, on])?.id).toBe(2);
        expect(primaryNumber([off])?.id).toBe(1);
        expect(primaryNumber([])).toBeNull();
    });
});

describe("PhoneSetup", () => {
    it("offers the three ways in, with keeping the existing number first", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([agentNumber()]) });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);

        const choices = await screen.findAllByRole("radio", { name: /number|mobile/i });
        expect(choices.slice(0, 3).map((c) => c.textContent)).toEqual([
            expect.stringContaining("Keep my existing number"),
            expect.stringContaining("Get a new number"),
            expect.stringContaining("My mobile is my business number"),
        ]);
        expect(choices[0].getAttribute("aria-checked")).toBe("true");
        expect(screen.getByText("Most common")).toBeTruthy();
    });

    it("shows the agent's number and the mobile code for the chosen rule, both copyable", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([agentNumber()]) });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);

        expect(await screen.findByText("+353 1 555 0142")).toBeTruthy();
        expect(screen.getByText("**61*+35315550142**20#")).toBeTruthy();
        expect(screen.getByText(/On most mobiles, dial this/)).toBeTruthy();
        expect(screen.getByText(/eir, Vodafone, Virgin Media, BT/)).toBeTruthy();
        expect(screen.getByText("##002#")).toBeTruthy();

        fireEvent.click(screen.getByRole("radio", { name: /When we’re busy/ }));
        expect(screen.getByText("**67*+35315550142#")).toBeTruthy();
        fireEvent.click(screen.getByRole("radio", { name: /All calls/ }));
        expect(screen.getByText("**21*+35315550142#")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
        await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith("**21*+35315550142#"));
        fireEvent.click(screen.getByRole("button", { name: "Copy number" }));
        await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith("+35315550142"));
    });

    it("sends outside-hours forwarding to the phone company, with no code", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([agentNumber()]) });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);
        fireEvent.click(await screen.findByRole("radio", { name: /Outside opening hours/ }));
        expect(screen.getByText(/Ask your phone company to forward calls outside your opening hours/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: "Copy code" })).toBeNull();
    });

    it("saves the choice when the owner says it's set up, then turns green on the first call", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([agentNumber()]) });
        const saved = {
            method: "keep_existing" as const,
            forward_when: "no_answer" as const,
            started_at: "2026-11-07T09:00:00Z",
        };
        mocks.putSetup.mockResolvedValue({
            data: setup([agentNumber({ setup: saved, check: { status: "waiting" } })]),
        });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);

        fireEvent.click(await screen.findByRole("button", { name: /I’ve set it up – check now/ }));
        await waitFor(() =>
            expect(mocks.putSetup).toHaveBeenCalledWith(
                expect.objectContaining({
                    path: { workflow_id: 7 },
                    body: { phone_number_id: 10, method: "keep_existing", forward_when: "no_answer" },
                }),
            ),
        );
        expect(await screen.findByText(/No call yet/)).toBeTruthy();

        // Saved and unchanged, so checking again only reads.
        mocks.getSetup.mockResolvedValue({
            data: setup([
                agentNumber({
                    setup: saved,
                    check: {
                        status: "received",
                        first_call_at: "2026-11-07T09:05:00Z",
                        first_call_run_id: 501,
                        forwarded_from: "+35315550100",
                    },
                }),
            ]),
        });
        fireEvent.click(screen.getByRole("button", { name: /I’ve set it up – check now/ }));
        expect(await screen.findByText(/It works/)).toBeTruthy();
        expect(screen.getByText("Forwarded from your number +353 1 555 0100.")).toBeTruthy();
        expect(mocks.putSetup).toHaveBeenCalledTimes(1);
    });

    it("asks for a number first when the agent has none, and shows Coming soon when LightMove numbers are off", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([], false) });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);

        expect(await screen.findByText(/Your agent needs its own number first/)).toBeTruthy();
        expect(screen.getByText("Coming soon")).toBeTruthy();
        expect(screen.getByRole("link", { name: "Ask us" }).getAttribute("href")).toMatch(/^mailto:/);
        expect(screen.queryByRole("button", { name: /check now/ })).toBeNull();
        expect(screen.getByRole("button", { name: /use my own phone provider account/ })).toBeTruthy();
    });

    it("gets a LightMove number for the agent", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([]) });
        mocks.search.mockResolvedValue({
            data: {
                country: "IE",
                numbers: [{ phone_number: "+35315550142", friendly_name: "015550142", kind: "local", locality: "Dublin" }],
            },
        });
        mocks.buy.mockResolvedValue({
            data: setup([
                agentNumber({
                    setup: { method: "new_number", started_at: "2026-11-07T09:00:00Z" },
                    check: { status: "waiting" },
                }),
            ]),
        });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);

        fireEvent.click(await screen.findByRole("radio", { name: /Get a new number/ }));
        fireEvent.click(screen.getByRole("button", { name: "Local number" }));
        await waitFor(() => expect(mocks.search).toHaveBeenCalledWith(expect.objectContaining({ query: { kind: "local" } })));
        fireEvent.click(await screen.findByRole("radio", { name: /\+353 1 555 0142/ }));
        fireEvent.click(screen.getByRole("button", { name: "Get this number" }));

        await waitFor(() =>
            expect(mocks.buy).toHaveBeenCalledWith(
                expect.objectContaining({ path: { workflow_id: 7 }, body: { phone_number: "+35315550142" } }),
            ),
        );
        expect(await screen.findByText(/Give this number to your callers/)).toBeTruthy();
        expect(screen.getByText("Provided by LightMove.")).toBeTruthy();
        // No price anywhere: billing for LightMove numbers isn't decided.
        expect(screen.queryByText(/€|\$|per month|price/i)).toBeNull();
    });

    it("shows the API's reason when a number can't be got", async () => {
        mocks.getSetup.mockResolvedValue({ data: setup([]) });
        mocks.search.mockResolvedValue({ error: { detail: "We couldn't look up numbers just now. Please try again." } });
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);
        fireEvent.click(await screen.findByRole("radio", { name: /Get a new number/ }));
        fireEvent.click(screen.getByRole("button", { name: "Mobile number" }));
        expect(await screen.findByText("We couldn't look up numbers just now. Please try again.")).toBeTruthy();
    });

    it("tells people without telephony access who can set the number up", () => {
        mocks.can.mockReturnValue(false);
        render(<PhoneSetup agentId={7} agentName="Bia Bistro" />);
        // It can't read the settings, so it doesn't claim no number is linked.
        expect(screen.getByText(/Only the owner or an admin can set up or change/)).toBeTruthy();
        expect(mocks.getSetup).not.toHaveBeenCalled();
    });
});
