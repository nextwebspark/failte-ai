import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfigSchemaForm, isTimeZoneKey } from "./ConfigSchemaForm";
import type { SchemaField } from "./schemaForm";

const timezone: SchemaField = {
    key: "timezone",
    label: "Timezone",
    kind: "string",
    required: true,
    nullable: false,
} as SchemaField;

describe("time zone settings", () => {
    it("knows a time zone setting by its name", () => {
        expect(isTimeZoneKey("timezone")).toBe(true);
        expect(isTimeZoneKey("time_zone")).toBe(true);
        expect(isTimeZoneKey("calendar_timezone")).toBe(true);
        expect(isTimeZoneKey("event_type_uri")).toBe(false);
    });

    it("offers a list of zones instead of a text box", () => {
        const onChange = vi.fn();
        render(
            <ConfigSchemaForm fields={[timezone]} values={{ timezone: "Europe/Dublin" }} errors={{}} onChange={onChange} />,
        );
        const select = screen.getByLabelText(/Timezone/) as HTMLSelectElement;
        expect(select.tagName).toBe("SELECT");
        expect(select.value).toBe("Europe/Dublin");
        fireEvent.change(select, { target: { value: "Europe/London" } });
        expect(onChange).toHaveBeenCalledWith("timezone", "Europe/London");
    });

    it("lets an optional zone stay unset, so the calendar's own applies", () => {
        render(
            <ConfigSchemaForm
                fields={[{ ...timezone, required: false, nullable: true } as SchemaField]}
                values={{ timezone: "" }}
                errors={{}}
                onChange={() => {}}
            />,
        );
        fireEvent.click(screen.getByText("More settings"));
        const select = screen.getByLabelText(/Timezone/) as HTMLSelectElement;
        expect(select.value).toBe("");
        expect(screen.getByText(/use the calendar's own time zone/)).toBeTruthy();
    });
});
