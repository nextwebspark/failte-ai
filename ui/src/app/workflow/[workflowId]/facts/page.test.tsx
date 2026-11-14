import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WhatYourAgentKnowsPage from "./page";
import type { AgentKnowledge } from "./useAgentKnowledge";

const mocks = vi.hoisted(() => ({
    get: vi.fn(),
    put: vi.fn(),
    can: vi.fn<(p: string) => boolean>(() => true),
    query: "",
    replace: vi.fn(),
    openTester: vi.fn(),
    setRailOpen: vi.fn(),
    setAiBooking: vi.fn(),
    followUps: vi.fn(),
    done: vi.fn(),
    knowledge: null as unknown as AgentKnowledge,
}));

vi.mock("next/navigation", () => ({
    useParams: () => ({ workflowId: "12" }),
    useSearchParams: () => new URLSearchParams(mocks.query),
    usePathname: () => "/workflow/12/facts",
    useRouter: () => ({ replace: mocks.replace }),
}));
vi.mock("@/context/AgentShellContext", () => ({
    useAgentShell: () => ({ openTester: mocks.openTester, setRailOpen: mocks.setRailOpen, agent: { name: "Restaurant bookings · Linen Quay Kitchen" } }),
}));
vi.mock("@/client/sdk.gen", () => ({
    listFollowUpsApiV1FollowUpsGet: mocks.followUps,
    markFollowUpDoneApiV1FollowUpsRunIdDonePost: mocks.done,
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet: mocks.get,
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut: mocks.put,
    setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut: mocks.setAiBooking,
    listSampleOrdersApiV1DemoSampleOrdersGet: () => Promise.resolve({ data: { available: false, orders: [] } }),
}));
vi.mock("@/components/layout/pageHeading", () => ({ useOwnsPageHeading: () => {} }));
vi.mock("./useAgentKnowledge", () => ({ useAgentKnowledge: () => mocks.knowledge }));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ can: mocks.can }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: "4" }, loading: false }) }));

// Radix measures the switch; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
} as unknown as typeof ResizeObserver;

const FACTS = [
    { key: "opening_hours", label: "Opening hours", type: "text", required: true, max_length: 300, value: "Tue-Sun 12-22" },
    { key: "extra_info", label: "Anything else callers often ask?", type: "textarea", required: false, max_length: 1500, value: "" },
];

const HIDDEN: AgentKnowledge = {
    greeting: { state: "hidden" },
    voice: { state: "hidden" },
    calendar: { state: "none", available: [] },
    phone: { state: "hidden" },
    setCalendar: vi.fn(),
};

describe("What your agent knows", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.knowledge = HIDDEN;
        mocks.query = "";
        mocks.can.mockImplementation(() => true);
        mocks.get.mockResolvedValue({ data: { facts: FACTS } });
        mocks.put.mockImplementation(async ({ body }) => ({
            data: { facts: FACTS.map((f) => ({ ...f, value: body.facts[f.key] ?? f.value })) },
        }));
        mocks.followUps.mockResolvedValue({ data: { items: [] } });
        mocks.done.mockResolvedValue({ data: {} });
    });

    it("has one main heading and the mock's panels, in plain words", async () => {
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["What your agent knows"]);
        expect(screen.getByText("Change these any time. Your agent uses them on the next call.")).toBeTruthy();
        for (const name of ["Your business", "Answers to common questions", "How it sounds", "Ready to take calls"]) {
            expect(screen.getByRole("heading", { level: 2, name })).toBeTruthy();
        }
        expect(screen.queryByText(/business facts/i)).toBeNull();
        // Nothing that isn't built, and no counts with no data behind them.
        expect(screen.queryByText(/text confirmation/i)).toBeNull();
        expect(screen.queryByText(/asked twice/i)).toBeNull();
        expect(screen.queryByText(/add a question/i)).toBeNull();
    });

    it("leaves the test rail closed here and open again for other screens", () => {
        const { unmount } = render(<WhatYourAgentKnowsPage />);
        expect(mocks.setRailOpen).toHaveBeenLastCalledWith(false);
        unmount();
        expect(mocks.setRailOpen).toHaveBeenLastCalledWith(true);
    });

    it("Try your agent opens the test panel in place", async () => {
        render(<WhatYourAgentKnowsPage />);
        const link = await screen.findByRole("link", { name: "Try your agent" });
        fireEvent.click(link);
        expect(mocks.openTester).toHaveBeenCalledTimes(1);
    });

    it("shows the greeting with the business's own words filled in, as they are typed", async () => {
        mocks.knowledge = {
            ...HIDDEN,
            greeting: { state: "ready", greeting: { kind: "text", text: "Hello, {{initial_context.business_name}}." } },
        };
        mocks.get.mockResolvedValue({
            data: {
                facts: [
                    { key: "business_name", label: "Business name", type: "text", required: true, max_length: 120, value: "Bia Bistro" },
                ],
            },
        });
        render(<WhatYourAgentKnowsPage />);
        expect(await screen.findByText("Hello, Bia Bistro.")).toBeTruthy();
        fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Café Rua" } });
        expect(screen.getByText("Hello, Café Rua.")).toBeTruthy();
    });

    it("offers bookings only when the agent books, with a working switch and booking times by day", async () => {
        mocks.knowledge = {
            ...HIDDEN,
            calendar: {
                state: "ready",
                provider: "google-calendar",
                connected: true,
                eventName: null,
                needsEvent: false,
                aiBooking: true,
                connectionId: "c1",
                rules: { service_periods: [{ days: [1, 2], first_start: "17:00", last_start: "21:30" }] },
            },
        };
        mocks.setAiBooking.mockResolvedValue({ data: {} });
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.getByText("Connected")).toBeTruthy();
        expect(screen.getByText("Calendar connected")).toBeTruthy();
        const days = screen.getByRole("list", { name: "Booking times by day" });
        expect(days.textContent).toContain("Tue5 pm–9:30 pm");
        expect(days.textContent).toContain("MonNo bookings");
        fireEvent.click(screen.getByRole("switch", { name: "Take bookings" }));
        await waitFor(() =>
            expect(mocks.setAiBooking).toHaveBeenCalledWith({
                path: { connection_id: "c1" },
                body: { ai_booking_enabled: false },
            }),
        );
    });

    it("says the agent books with Calendly, and which event", async () => {
        mocks.knowledge = {
            ...HIDDEN,
            calendar: {
                state: "ready",
                provider: "calendly",
                connected: true,
                eventName: "Consultation",
                needsEvent: false,
                aiBooking: true,
                connectionId: "c2",
                rules: {},
            },
        };
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.getByText(/Checks free times in your Calendly and books them\./)).toBeTruthy();
        expect(screen.getByText(/Callers book “Consultation”/)).toBeTruthy();
        expect(screen.getByText("Connected")).toBeTruthy();
        expect(screen.getByText("Calendar connected")).toBeTruthy();
        expect(screen.queryByText(/Google Calendar/)).toBeNull();
        // Calendly keeps its own hours: no booking times row.
        expect(screen.queryByRole("list", { name: "Booking times by day" })).toBeNull();
    });

    it("asks for a Calendly event before the agent can book", async () => {
        mocks.knowledge = {
            ...HIDDEN,
            calendar: {
                state: "ready",
                provider: "calendly",
                connected: true,
                eventName: null,
                needsEvent: true,
                aiBooking: true,
                connectionId: "c2",
                rules: {},
            },
        };
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.getByText("Choose your Calendly event")).toBeTruthy();
        expect(screen.queryByText("Calendar connected")).toBeNull();
    });

    it("has no bookings row or switch for an agent that doesn't book", async () => {
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.queryByText("Take bookings")).toBeNull();
        expect(screen.queryByRole("switch")).toBeNull();
    });

    it("offers a connected calendar the agent doesn't use yet, and attaches it", async () => {
        const chooseCalendar = vi.fn().mockResolvedValue(undefined);
        mocks.knowledge = {
            ...HIDDEN,
            calendar: { state: "none", available: [{ toolUuid: "cal-1", provider: "calendly", name: "Calendly" }] },
            chooseCalendar,
        };
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.getByText("Take bookings")).toBeTruthy();
        expect(screen.getByText(/Calendly is connected, but this agent doesn't use it yet/)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Book with Calendly" }));
        await waitFor(() => expect(chooseCalendar).toHaveBeenCalledWith("cal-1"));
        expect(toast.success).toHaveBeenCalledWith("Your agent books with this calendar from the next call.");
    });

    it("doesn't offer the calendar to people who can't change the agent", async () => {
        mocks.can.mockImplementation((p) => p !== "agents:facts");
        mocks.knowledge = {
            ...HIDDEN,
            calendar: { state: "none", available: [{ toolUuid: "cal-1", provider: "calendly", name: "Calendly" }] },
            chooseCalendar: vi.fn(),
        };
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(screen.queryByRole("button", { name: "Book with Calendly" })).toBeNull();
    });

    it("says why attaching the calendar failed", async () => {
        mocks.knowledge = {
            ...HIDDEN,
            calendar: { state: "none", available: [{ toolUuid: "cal-1", provider: "calendly", name: "Calendly" }] },
            chooseCalendar: vi.fn().mockRejectedValue(new Error("That calendar isn't connected to this workspace.")),
        };
        render(<WhatYourAgentKnowsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Book with Calendly" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("That calendar isn't connected to this workspace."));
    });

    it("lists what is ready from real data, and says when no phone number rings the agent", async () => {
        mocks.knowledge = { ...HIDDEN, phone: { state: "ready", numbers: [] } };
        render(<WhatYourAgentKnowsPage />);
        expect(await screen.findByText("No phone number linked yet")).toBeTruthy();
        expect(screen.getByText("Business details added")).toBeTruthy();
        expect(screen.getByText("Done:")).toBeTruthy();
        expect(screen.getByText("To do:")).toBeTruthy();
    });

    it("opens the test panel once when arriving from the Create agent wizard", async () => {
        mocks.query = "onboarding=web_call";
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(mocks.openTester).toHaveBeenCalledTimes(1);
        expect(mocks.replace).toHaveBeenCalledWith("/workflow/12/facts", { scroll: false });
    });

    it("leaves the test panel alone on a normal visit", async () => {
        render(<WhatYourAgentKnowsPage />);
        await screen.findByLabelText("Opening hours");
        expect(mocks.openTester).not.toHaveBeenCalled();
        expect(mocks.replace).not.toHaveBeenCalled();
    });

    it("lets the owner change what the agent tells callers", async () => {
        render(<WhatYourAgentKnowsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        expect((hours as HTMLInputElement).value).toBe("Tue-Sun 12-22");
        const save = screen.getByRole("button", { name: "Save changes" });
        expect(save.hasAttribute("disabled")).toBe(true);

        fireEvent.change(hours, { target: { value: "Wed-Sun 17-23" } });
        fireEvent.click(save);

        await waitFor(() =>
            expect(mocks.put).toHaveBeenCalledWith({
                path: { workflow_id: 12 },
                body: { facts: { opening_hours: "Wed-Sun 17-23" } },
            }),
        );
    });

    it("is read-only for people who can't edit facts", async () => {
        mocks.can.mockImplementation(() => false);
        render(<WhatYourAgentKnowsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        expect(hours.hasAttribute("disabled")).toBe(true);
        expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
        expect(screen.getByText("What your agent tells callers. The owner or an admin keeps it up to date.")).toBeTruthy();
        // Starting a test call needs agents:write.
        expect(screen.queryByRole("link", { name: /try your agent/i })).toBeNull();
        // The builder link is for people who may edit the agent.
        expect(screen.queryByRole("link", { name: "Open advanced setup" })).toBeNull();
    });

    it("explains agents without facts", async () => {
        mocks.get.mockResolvedValue({ data: { facts: [] } });
        render(<WhatYourAgentKnowsPage />);
        expect(await screen.findByText("This agent has no business details to edit here.")).toBeTruthy();
    });

    it("shows a load error with Try again, then recovers", async () => {
        mocks.get.mockResolvedValueOnce({ error: { detail: "Agent not found" } });
        render(<WhatYourAgentKnowsPage />);
        const alert = await screen.findByRole("alert");
        expect(alert.textContent).toContain("We couldn't load what your agent knows");
        expect(alert.textContent).not.toContain("Agent not found");
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        expect(await screen.findByLabelText("Opening hours")).toBeTruthy();
        expect(mocks.get).toHaveBeenCalledTimes(2);
    });

    it("handles a network failure while loading", async () => {
        mocks.get.mockRejectedValueOnce(new TypeError("Failed to fetch"));
        render(<WhatYourAgentKnowsPage />);
        expect((await screen.findByRole("alert")).textContent).toContain("We couldn't load what your agent knows");
        expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    });

    it("won't save a required answer left blank, and says which", async () => {
        render(<WhatYourAgentKnowsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        expect(hours.hasAttribute("required")).toBe(true);
        fireEvent.change(hours, { target: { value: "   " } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        expect(mocks.put).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith("Fill in the required answers before saving.");
        expect(hours.getAttribute("aria-invalid")).toBe("true");
        const message = document.getElementById(hours.getAttribute("aria-describedby") ?? "");
        expect(message?.textContent).toContain("Your agent needs this answer");

        // Fixing it clears the message and saves.
        fireEvent.change(hours, { target: { value: "Mon-Fri 9-5" } });
        expect(hours.getAttribute("aria-invalid")).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    });

    it("lets an optional answer be blank", async () => {
        render(<WhatYourAgentKnowsPage />);
        const extra = await screen.findByLabelText(/Anything else callers often ask/);
        fireEvent.change(extra, { target: { value: "Parking at the back" } });
        fireEvent.change(extra, { target: { value: "" } });
        fireEvent.change(screen.getByLabelText("Opening hours"), { target: { value: "Mon-Fri 9-5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() =>
            expect(mocks.put).toHaveBeenCalledWith({
                path: { workflow_id: 12 },
                body: { facts: { opening_hours: "Mon-Fri 9-5" } },
            }),
        );
    });

    it("sends only one save on a double click", async () => {
        let resolve: (value: unknown) => void = () => {};
        mocks.put.mockReturnValue(new Promise((r) => (resolve = r)));
        render(<WhatYourAgentKnowsPage />);
        fireEvent.change(await screen.findByLabelText("Opening hours"), { target: { value: "Mon-Fri 9-5" } });
        const save = screen.getByRole("button", { name: "Save changes" });
        fireEvent.click(save);
        fireEvent.click(save);
        expect(mocks.put).toHaveBeenCalledTimes(1);
        expect(screen.getByRole("button", { name: "Saving…" }).hasAttribute("disabled")).toBe(true);
        resolve({ data: { facts: FACTS.map((f) => (f.key === "opening_hours" ? { ...f, value: "Mon-Fri 9-5" } : f)) } });
        await waitFor(() => expect(toast.success).toHaveBeenCalled());
    });

    it("keeps the owner's typing when the save is refused", async () => {
        mocks.put.mockResolvedValue({ error: { detail: "Opening hours is too long." } });
        render(<WhatYourAgentKnowsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        fireEvent.change(hours, { target: { value: "Mon-Fri 9-5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Opening hours is too long."));
        expect((hours as HTMLInputElement).value).toBe("Mon-Fri 9-5");
        expect(screen.getByRole("button", { name: "Save changes" }).hasAttribute("disabled")).toBe(false);
    });

    it("handles a network failure while saving", async () => {
        mocks.put.mockRejectedValue(new TypeError("Failed to fetch"));
        render(<WhatYourAgentKnowsPage />);
        fireEvent.change(await screen.findByLabelText("Opening hours"), { target: { value: "Mon-Fri 9-5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't save. Please try again."));
        expect(screen.getByRole("button", { name: "Save changes" }).hasAttribute("disabled")).toBe(false);
    });

    it("Discard puts the saved answers back", async () => {
        render(<WhatYourAgentKnowsPage />);
        const hours = await screen.findByLabelText("Opening hours");
        const discard = screen.getByRole("button", { name: "Discard" });
        expect(discard.hasAttribute("disabled")).toBe(true);
        fireEvent.change(hours, { target: { value: "Closed" } });
        expect(screen.getByText("1 unsaved change")).toBeTruthy();
        fireEvent.click(discard);
        expect((hours as HTMLInputElement).value).toBe("Tue-Sun 12-22");
        expect(discard.hasAttribute("disabled")).toBe(true);
    });

    it("shows questions the agent couldn't answer, and adds an answer to the list", async () => {
        mocks.followUps.mockResolvedValue({
            data: {
                items: [
                    {
                        run_id: 106,
                        workflow_id: 12,
                        kind: "unanswered_question",
                        created_at: "2026-11-05T12:00:00Z",
                        questions: ["Do you have gluten-free pasta?"],
                    },
                ],
            },
        });
        mocks.get.mockResolvedValue({
            data: { facts: FACTS.map((f) => (f.key === "extra_info" ? { ...f, value: "Q: Parking? A: Henry Street." } : f)) },
        });
        render(<WhatYourAgentKnowsPage />);
        expect(await screen.findByText("No answer yet. Add one so your agent can help next time.")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /add answer/i }));
        fireEvent.change(await screen.findByLabelText("Your answer"), { target: { value: "Yes, just ask." } });
        fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
        await waitFor(() =>
            expect(mocks.put).toHaveBeenCalledWith({
                path: { workflow_id: 12 },
                body: { facts: { extra_info: "Q: Parking? A: Henry Street.\nQ: Do you have gluten-free pasta? A: Yes, just ask." } },
            }),
        );
        await waitFor(() =>
            expect(mocks.done).toHaveBeenCalledWith({ path: { run_id: 106 }, query: { kind: "unanswered_question" } }),
        );
    });

    describe("opening hours as times", () => {
        const SCHEDULE = {
            days: [
                [],
                ...Array(6).fill([
                    { open: "12:00", close: "15:00" },
                    { open: "17:00", close: "22:00" },
                ]),
            ],
            timezone: "Europe/Dublin",
            transfer_only_when_open: true,
            note: null,
        };
        const TRANSFER = {
            key: "transfer_number",
            label: "Number to put callers through to a person",
            type: "phone",
            required: false,
            max_length: 40,
            value: "+353871234567",
        };

        it("keeps free text, offering to set the hours as times without guessing them", async () => {
            render(<WhatYourAgentKnowsPage />);
            expect(((await screen.findByLabelText("Opening hours")) as HTMLInputElement).value).toBe("Tue-Sun 12-22");
            fireEvent.click(screen.getByRole("button", { name: "Set your hours as times" }));
            // A plain starting week, not a reading of "Tue-Sun 12-22".
            expect(screen.getByRole("button", { name: "Monday: 9 am–5 pm. Change" })).toBeTruthy();
            expect(screen.getByRole("button", { name: "Sunday: Closed. Change" })).toBeTruthy();
            fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
            await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
            const body = mocks.put.mock.calls[0][0].body;
            expect(body.facts).toEqual({});
            expect(body.opening_hours_schedule.days[0]).toEqual([{ open: "09:00", close: "17:00" }]);
        });

        it("shows saved times as day chips and edits a day", async () => {
            mocks.get.mockResolvedValue({ data: { facts: [...FACTS, TRANSFER], opening_hours_schedule: SCHEDULE } });
            render(<WhatYourAgentKnowsPage />);
            const monday = await screen.findByRole("button", { name: "Monday: Closed. Change" });
            expect(screen.getByRole("button", { name: "Tuesday: 12–3 pm and 5–10 pm. Change" })).toBeTruthy();
            expect(screen.getByText(/Your agent says:/).parentElement?.textContent).toContain(
                "Tuesday to Sunday 12 to 3 pm and 5 to 10 pm, closed Monday",
            );
            fireEvent.click(monday);
            fireEvent.click(screen.getByRole("switch", { name: "Open on Monday" }));
            expect(screen.getByRole("button", { name: "Monday: 9 am–5 pm. Change" })).toBeTruthy();
            fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
            await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
            expect(mocks.put.mock.calls[0][0].body.opening_hours_schedule.days[0]).toEqual([{ open: "09:00", close: "17:00" }]);
        });

        it("passes calls only during opening hours, and can be switched off", async () => {
            mocks.get.mockResolvedValue({ data: { facts: [...FACTS, TRANSFER], opening_hours_schedule: SCHEDULE } });
            render(<WhatYourAgentKnowsPage />);
            const toggle = await screen.findByRole("switch", { name: "Only during opening hours" });
            expect(toggle.getAttribute("aria-checked")).toBe("true");
            expect(screen.getByText(/takes a message, which appears in Follow-ups/)).toBeTruthy();
            fireEvent.click(toggle);
            fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
            await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
            expect(mocks.put.mock.calls[0][0].body.opening_hours_schedule.transfer_only_when_open).toBe(false);
        });

        it("can go back to writing the hours out", async () => {
            mocks.get.mockResolvedValue({ data: { facts: FACTS, opening_hours_schedule: SCHEDULE } });
            render(<WhatYourAgentKnowsPage />);
            fireEvent.click(await screen.findByRole("button", { name: "Write your hours out instead" }));
            expect(((await screen.findByLabelText("Opening hours")) as HTMLInputElement).value).toBe("Tue-Sun 12-22");
            fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
            await waitFor(() =>
                expect(mocks.put).toHaveBeenCalledWith({
                    path: { workflow_id: 12 },
                    body: { facts: {}, opening_hours_schedule: null },
                }),
            );
        });
    });

    it("switches languages on with English always on, and saves them as names", async () => {
        const languages = {
            key: "agent_languages",
            label: "Languages your agent speaks",
            type: "languages",
            required: false,
            max_length: 300,
            value: "",
        };
        mocks.get.mockResolvedValue({ data: { facts: [...FACTS, languages] } });
        render(<WhatYourAgentKnowsPage />);
        const english = await screen.findByRole("button", { name: "English (always on)" });
        expect(english.getAttribute("aria-pressed")).toBe("true");
        expect(english.hasAttribute("disabled")).toBe(true);
        expect(screen.getByText(/read in your agent's own voice/)).toBeTruthy();
        const polish = screen.getByRole("button", { name: "Polish" });
        expect(polish.getAttribute("aria-pressed")).toBe("false");
        fireEvent.click(polish);
        expect(polish.getAttribute("aria-pressed")).toBe("true");
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
        await waitFor(() =>
            expect(mocks.put).toHaveBeenCalledWith({
                path: { workflow_id: 12 },
                body: { facts: { agent_languages: "English, Polish" } },
            }),
        );
    });
});
