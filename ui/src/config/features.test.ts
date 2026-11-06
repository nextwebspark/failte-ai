import { afterEach, describe, expect, it } from "vitest";

import { getNavSections, getRequiredPermission, NAV_SECTIONS } from "@/components/layout/navConfig";
import { getUsageFilterAttributes, usageFilterAttributes } from "@/lib/filterAttributes";

import {
    DEFAULT_FEATURE_FLAGS,
    featureForRoute,
    FEATURES,
    getFeatureFlags,
    hasRuntimeFeatureFlags,
    isFeatureEnabled,
    isSwitchedOffRoute,
    parseFeatureFlags,
    setRuntimeFeatureFlags,
    subscribeToFeatureFlags,
} from "./features";

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

// Platform admins switch the areas at runtime; the values above are the
// defaults until the switches are read.
describe("runtime feature switches", () => {
    afterEach(() => setRuntimeFeatureFlags(null));

    it("uses the defaults until the switches are read", () => {
        expect(hasRuntimeFeatureFlags()).toBe(false);
        expect(getFeatureFlags()).toEqual(DEFAULT_FEATURE_FLAGS);
        expect(isFeatureEnabled("campaigns")).toBe(false);
    });

    it("follows the switches read from the API", () => {
        const seen: boolean[] = [];
        const unsubscribe = subscribeToFeatureFlags(() => seen.push(isFeatureEnabled("campaigns")));
        setRuntimeFeatureFlags({ campaigns: true, skills: false });
        unsubscribe();

        expect(seen).toEqual([true]);
        expect(hasRuntimeFeatureFlags()).toBe(true);
        expect(isSwitchedOffRoute("/campaigns/12")).toBe(false);
        expect(isSwitchedOffRoute("/skills")).toBe(true);
        const urls = getNavSections(getFeatureFlags()).flatMap((section) => section.items.map((item) => item.url));
        expect(urls).toContain("/campaigns");
        expect(urls).not.toContain("/skills");
    });

    it("offers the Campaign ID filter only while Campaigns is on", () => {
        expect(getUsageFilterAttributes(true).map((a) => a.id)).toContain("campaignId");
        expect(getUsageFilterAttributes(false).map((a) => a.id)).not.toContain("campaignId");
    });

    it("names the area a path belongs to", () => {
        expect(featureForRoute("/campaigns/new")).toBe("campaigns");
        expect(featureForRoute("/skills")).toBe("skills");
        expect(featureForRoute("/skillset")).toBeNull();
        expect(featureForRoute("/overview")).toBeNull();
    });

    it("reads an API body defensively", () => {
        expect(parseFeatureFlags({ features: { campaigns: true } })).toEqual({ campaigns: true, skills: false });
        expect(parseFeatureFlags({ features: { campaigns: "yes", retired: true } })).toEqual(DEFAULT_FEATURE_FLAGS);
        expect(parseFeatureFlags({ detail: "Unauthorized" })).toBeNull();
        expect(parseFeatureFlags(null)).toBeNull();
    });
});
