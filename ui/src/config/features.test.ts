import { describe, expect, it } from "vitest";

import { getRequiredPermission, NAV_SECTIONS } from "@/components/layout/navConfig";
import { usageFilterAttributes } from "@/lib/filterAttributes";

import { FEATURES, isSwitchedOffRoute } from "./features";

// Campaigns and Skills are built but not offered yet (config/features.ts).
describe("switched-off product areas", () => {
    it("keeps Campaigns and Skills switched off", () => {
        expect(FEATURES).toEqual({ campaigns: false, skills: false });
    });

    it("leaves them out of the left nav", () => {
        const urls = NAV_SECTIONS.flatMap((section) => section.items.map((item) => item.url));
        expect(urls).not.toContain("/campaigns");
        expect(urls).not.toContain("/skills");
        expect(urls).toContain("/workflow");
    });

    it("still guards their routes by permission", () => {
        expect(getRequiredPermission("/campaigns")).toBe("campaigns:read");
        expect(getRequiredPermission("/skills")).toBe("agents:read");
    });

    it("marks their pages for the redirect to Overview, and nothing else", () => {
        for (const path of ["/campaigns", "/campaigns/new", "/campaigns/12/edit", "/skills", "/skills/library/abc"]) {
            expect(isSwitchedOffRoute(path)).toBe(true);
        }
        for (const path of ["/overview", "/workflow/7/settings", "/skillset", "/usage", "/"]) {
            expect(isSwitchedOffRoute(path)).toBe(false);
        }
    });

    it("drops the Campaign ID filter from Agent runs", () => {
        const ids = usageFilterAttributes.map((attribute) => attribute.id);
        expect(ids).not.toContain("campaignId");
        expect(ids).toContain("workflowId");
    });
});
