import { describe, expect, it } from "vitest";

import { firstName, greetingFor, timeOfDayGreeting } from "./greeting";

describe("greeting", () => {
    it("uses the first word of the display name, then the name, then the email", () => {
        expect(firstName({ displayName: "Naveen Ennis" })).toBe("Naveen");
        expect(firstName({ name: "  Mary   Byrne " })).toBe("Mary");
        expect(firstName({ email: "mary.byrne@example.ie" })).toBe("Mary");
        expect(firstName({ email: "sean+bookings@example.ie" })).toBe("Sean");
        expect(firstName({})).toBe("");
        expect(firstName(null)).toBe("");
    });

    it("says morning, afternoon or evening by the local hour", () => {
        expect(timeOfDayGreeting(new Date(2026, 10, 6, 0, 30))).toBe("Good morning");
        expect(timeOfDayGreeting(new Date(2026, 10, 6, 11, 59))).toBe("Good morning");
        expect(timeOfDayGreeting(new Date(2026, 10, 6, 12, 0))).toBe("Good afternoon");
        expect(timeOfDayGreeting(new Date(2026, 10, 6, 17, 59))).toBe("Good afternoon");
        expect(timeOfDayGreeting(new Date(2026, 10, 6, 18, 0))).toBe("Good evening");
    });

    it("leaves the name out when there isn't one", () => {
        const nine = new Date(2026, 10, 6, 9);
        expect(greetingFor({ name: "Aoife Ryan" }, nine)).toBe("Good morning, Aoife");
        expect(greetingFor(undefined, nine)).toBe("Good morning");
    });
});
