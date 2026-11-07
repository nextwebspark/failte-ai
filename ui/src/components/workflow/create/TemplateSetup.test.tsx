import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IntegrationConnectionResponse, WorkflowTemplateResponse } from "@/client/types.gen";

import { TemplateSetup } from "./TemplateSetup";
import type { AppointmentHours } from "./useAppointmentHours";
import type { ConnectStatus, IntegrationConnect } from "./useIntegrationConnect";

const TEMPLATE = {
    id: 1,
    template_name: "Clinic receptionist",
    template_description: "",
    template_json: { nodes: [{ type: "startCall", data: { greeting: "Hello, {{business_name}}." } }] },
    setup_fields: [],
    integrations: ["google-calendar"],
    created_at: "2026-11-06T00:00:00Z",
} as unknown as WorkflowTemplateResponse;

const HOURS = { field: null } as unknown as AppointmentHours;

function connect(status: ConnectStatus, config: Record<string, unknown> = {}): IntegrationConnect {
    return {
        status,
        connection:
            status === "connected"
                ? ({ id: "c", provider: "x", config, tool_uuids: ["t"] } as unknown as IntegrationConnectionResponse)
                : null,
        connectedHere: false,
        error: null,
        connect: vi.fn(),
        cancel: vi.fn(),
    };
}

function setup(google: IntegrationConnect, calendly: IntegrationConnect, bookWith: "google-calendar" | "calendly") {
    const onBookWithChange = vi.fn();
    render(
        <TemplateSetup
            template={TEMPLATE}
            answers={{}}
            errors={{}}
            onAnswer={vi.fn()}
            calendar={google}
            calendly={calendly}
            bookWith={bookWith}
            onBookWithChange={onBookWithChange}
            useCalendar
            onUseCalendarChange={vi.fn()}
            hours={HOURS}
        />,
    );
    return { onBookWithChange };
}

describe("TemplateSetup with Calendly", () => {
    it("books with a connected Calendly when Google Calendar isn't connected", () => {
        setup(connect("ready"), connect("connected", { event_type_name: "Consultation" }), "calendly");
        expect(screen.getByText("Calendly connected")).toBeTruthy();
        expect(screen.getByText(/books callers into “Consultation”/)).toBeTruthy();
        expect(screen.getByText(/Your hours come from Calendly/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: /Connect Google Calendar/ })).toBeNull();
        expect(screen.getByText("Books into your calendar")).toBeTruthy();
    });

    it("says an event still needs choosing", () => {
        setup(connect("ready"), connect("connected", {}), "calendly");
        expect(screen.getByText(/Choose the event in Integrations/)).toBeTruthy();
    });

    it("lets the owner pick when both calendars are connected", () => {
        const { onBookWithChange } = setup(connect("connected"), connect("connected", {}), "google-calendar");
        expect(screen.getByText("Google Calendar connected")).toBeTruthy();
        fireEvent.click(screen.getByRole("radio", { name: "Book with Calendly" }));
        expect(onBookWithChange).toHaveBeenCalledWith("calendly");
    });

    it("points to Integrations for Calendly when nothing is connected", () => {
        setup(connect("ready"), connect("in_integrations"), "google-calendar");
        expect(screen.getByRole("button", { name: /Connect Google Calendar/ })).toBeTruthy();
        expect(screen.getByRole("link", { name: /Connect it in Integrations/ }).getAttribute("href")).toBe(
            "/integrations",
        );
    });
});
