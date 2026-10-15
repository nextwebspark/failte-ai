import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { skillsLoadedFrom, SkillsLoadedSection } from "./SkillsLoadedSection";

describe("skillsLoadedFrom", () => {
    it("keeps well-formed records and skips the rest", () => {
        expect(
            skillsLoadedFrom({
                skills_loaded: [
                    { name: "returns-policy", node: "Support", via: "load_skill", at: "2026-10-10T10:00:00Z" },
                    { node: "x" },
                    "junk",
                ],
            }),
        ).toEqual([{ name: "returns-policy", node: "Support", via: "load_skill", at: "2026-10-10T10:00:00Z" }]);
        expect(skillsLoadedFrom({ skills_loaded: "nope" })).toEqual([]);
        expect(skillsLoadedFrom(null)).toEqual([]);
    });
});

describe("SkillsLoadedSection", () => {
    it("renders nothing without loads", () => {
        const { container } = render(<SkillsLoadedSection gatheredContext={{}} />);
        expect(container.textContent).toBe("");
    });

    it("lists loaded and preloaded skills with their step", () => {
        render(
            <SkillsLoadedSection
                gatheredContext={{
                    skills_loaded: [
                        { name: "returns-policy", node: "Support", via: "load_skill" },
                        { name: "greeting", node: "Start", via: "preload" },
                    ],
                }}
            />,
        );
        expect(screen.getByText("Skills used")).toBeTruthy();
        expect(screen.getByText("Loaded")).toBeTruthy();
        expect(screen.getByText("Preloaded")).toBeTruthy();
        expect(screen.getByText("in Support")).toBeTruthy();
    });
});
