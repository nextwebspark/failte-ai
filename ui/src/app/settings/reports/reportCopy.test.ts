import { describe as group, expect, it } from "vitest";

import { addressProblem, clockLabel, describe, sentLabel, zoneLabel } from "./reportCopy";

group("reportCopy", () => {
  it("writes clock times the Irish way", () => {
    expect(clockLabel("18:00")).toBe("6 pm");
    expect(clockLabel("09:30")).toBe("9:30 am");
    expect(clockLabel("00:00")).toBe("12 am");
    expect(clockLabel("12:15")).toBe("12:15 pm");
  });

  it("names the zone by its city", () => {
    expect(zoneLabel("Europe/Dublin")).toBe("Dublin time");
    expect(zoneLabel("America/New_York")).toBe("New York time");
  });

  it("says what each report covers and when it arrives", () => {
    expect(describe("daily", "17:30")).toEqual({
      covers: "The last 24 hours of calls, 5:30 pm to 5:30 pm.",
      arrives: "Every day at 5:30 pm.",
    });
    expect(describe("daily", "00:00").covers).toBe("Yesterday's calls, the whole day.");
    expect(describe("weekly", "18:00").arrives).toBe("Mondays at 8 am.");
    expect(describe("monthly", "18:00").arrives).toBe("On the 1st at 8 am.");
  });

  it("labels the last period sent", () => {
    expect(sentLabel("daily", "2026-11-06")).toBe("6 Nov");
    expect(sentLabel("weekly", "2026-W05")).toBe("week 5");
    expect(sentLabel("monthly", "2026-10")).toBe("Oct 2026");
    expect(sentLabel("daily", undefined)).toBeNull();
  });

  it("checks an address before adding it", () => {
    expect(addressProblem("", [], 10)).toBe("Type an email address.");
    expect(addressProblem("not-an-email", [], 10)).toMatch(/doesn't look like/);
    expect(addressProblem("A@b.ie", ["a@B.ie"], 10)).toMatch(/already/);
    expect(addressProblem("x@b.ie", ["a@b.ie"], 1)).toMatch(/up to 1/);
    expect(addressProblem(" chef@bia.ie ", [], 10)).toBeNull();
  });
});
