import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { PropertySpec, SkillSummaryResponse } from "@/client/types.gen";

import { PropertyInput } from "./renderer/PropertyInput";
import { PreloadSkillSelector, scopeOf, SkillScopeSelector, valueForScope } from "./SkillSelector";

vi.mock("next/link", () => ({
    default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

function skill(uuid: string, name: string): SkillSummaryResponse {
    return {
        skill_uuid: uuid,
        name,
        description: `${name} description`,
        status: "active",
        allowed_tool_uuids: null,
        source_library_uuid: null,
        source_version: null,
        is_modified: false,
        update_available: false,
        created_by: 1,
        created_at: "",
        updated_at: "",
    };
}

const SKILLS = [skill("s-1", "returns-policy"), skill("s-2", "booking")];

describe("skill scope semantics", () => {
    it("maps null/undefined to all, [] to none and a list to selected", () => {
        expect(scopeOf(undefined)).toBe("all");
        expect(scopeOf(null)).toBe("all");
        expect(scopeOf([])).toBe("none");
        expect(scopeOf(["s-1"])).toBe("selected");
    });

    it("stores undefined for all, [] for none and keeps picks for selected", () => {
        expect(valueForScope("all", ["s-1"])).toBeUndefined();
        expect(valueForScope("none", ["s-1"])).toEqual([]);
        expect(valueForScope("selected", ["s-1"])).toEqual(["s-1"]);
        expect(valueForScope("selected", null)).toEqual([]);
    });
});

describe("SkillScopeSelector", () => {
    it("starts on 'All skills' for an unset value and switches to None ([]) and back (undefined)", () => {
        const onChange = vi.fn();
        render(<SkillScopeSelector value={undefined} onChange={onChange} skills={SKILLS} label="Skills" />);

        expect(screen.getByRole("radio", { name: /All skills/ }).getAttribute("aria-checked")).toBe("true");
        expect(screen.queryByRole("checkbox")).toBeNull();

        fireEvent.click(screen.getByRole("radio", { name: /None/ }));
        expect(onChange).toHaveBeenLastCalledWith([]);

        fireEvent.click(screen.getByRole("radio", { name: /All skills/ }));
        expect(onChange).toHaveBeenLastCalledWith(undefined);
    });

    it("shows [] as None", () => {
        render(<SkillScopeSelector value={[]} onChange={vi.fn()} skills={SKILLS} label="Skills" />);
        expect(screen.getByRole("radio", { name: /None/ }).getAttribute("aria-checked")).toBe("true");
    });

    it("lets you pick skills once 'Selected' is chosen, staying on Selected with nothing ticked", () => {
        const onChange = vi.fn();
        const { rerender } = render(
            <SkillScopeSelector value={undefined} onChange={onChange} skills={SKILLS} label="Skills" />,
        );
        fireEvent.click(screen.getByRole("radio", { name: /Selected skills/ }));
        expect(onChange).toHaveBeenLastCalledWith([]);

        rerender(<SkillScopeSelector value={[]} onChange={onChange} skills={SKILLS} label="Skills" />);
        expect(screen.getByRole("radio", { name: /Selected skills/ }).getAttribute("aria-checked")).toBe("true");
        expect(screen.getByText(/until you pick one, this step offers no skills/)).toBeTruthy();

        fireEvent.click(screen.getByRole("checkbox", { name: /booking/ }));
        expect(onChange).toHaveBeenLastCalledWith(["s-2"]);
    });

    it("lists a selected skill that is no longer active so it can be removed", () => {
        const onChange = vi.fn();
        render(<SkillScopeSelector value={["gone", "s-1"]} onChange={onChange} skills={SKILLS} label="Skills" />);
        fireEvent.click(screen.getByRole("checkbox", { name: /Archived or unknown skill/ }));
        expect(onChange).toHaveBeenLastCalledWith(["s-1"]);
    });
});

describe("PreloadSkillSelector", () => {
    it("is a plain multi-select that clears to undefined", () => {
        const onChange = vi.fn();
        const { rerender } = render(
            <PreloadSkillSelector value={undefined} onChange={onChange} skills={SKILLS} label="Preloaded Skills" />,
        );
        expect(screen.queryByRole("radio")).toBeNull();
        fireEvent.click(screen.getByRole("checkbox", { name: /returns-policy/ }));
        expect(onChange).toHaveBeenLastCalledWith(["s-1"]);

        rerender(<PreloadSkillSelector value={["s-1"]} onChange={onChange} skills={SKILLS} label="Preloaded Skills" />);
        fireEvent.click(screen.getByRole("checkbox", { name: /returns-policy/ }));
        expect(onChange).toHaveBeenLastCalledWith(undefined);
    });
});

describe("PropertyInput skill_refs", () => {
    const context = { tools: [], documents: [], recordings: [], skills: SKILLS };
    const spec = (name: string, display: string): PropertySpec =>
        ({ name, type: "skill_refs", display_name: display, required: false }) as PropertySpec;

    it("renders the tri-state picker for skill_uuids and the list for preload_skill_uuids", () => {
        const { unmount } = render(
            <PropertyInput spec={spec("skill_uuids", "Skills")} value={null} onChange={vi.fn()} context={context} />,
        );
        expect(screen.getByRole("radio", { name: /All skills/ })).toBeTruthy();
        unmount();

        render(
            <PropertyInput
                spec={spec("preload_skill_uuids", "Preloaded Skills")}
                value={["s-2"]}
                onChange={vi.fn()}
                context={context}
            />,
        );
        expect(screen.queryByRole("radio")).toBeNull();
        expect(screen.getByRole("checkbox", { name: /booking/ }).getAttribute("aria-checked")).toBe("true");
    });
});
