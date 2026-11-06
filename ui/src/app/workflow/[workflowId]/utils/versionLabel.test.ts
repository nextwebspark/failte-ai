import { describe, expect, it } from "vitest";

import { versionLabel } from "./versionLabel";

describe("versionLabel", () => {
    it("calls a published version live", () => {
        expect(versionLabel(1, "published")).toBe("Version 1 · Live");
    });

    it("marks a draft", () => {
        expect(versionLabel(3, "draft")).toBe("Version 3 · Draft");
    });

    it("shows just the number for older versions", () => {
        expect(versionLabel(2, "archived")).toBe("Version 2");
        expect(versionLabel(4, null)).toBe("Version 4");
    });
});
