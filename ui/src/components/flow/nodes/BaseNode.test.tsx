import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BaseNode } from "./BaseNode";

function classesFor(props: Parameters<typeof BaseNode>[0]) {
    const { container } = render(<BaseNode {...props} />);
    return (container.firstChild as HTMLElement).className.split(" ");
}

describe("BaseNode states", () => {
    it("a selected step gets the brand border", () => {
        expect(classesFor({ selected: true })).toContain("border-brand");
    });

    it("an invalid step stays red when selected", () => {
        const classes = classesFor({ selected: true, invalid: true });
        expect(classes).toContain("border-danger");
        expect(classes).not.toContain("border-brand");
    });

    it("the live call's step is orange even when invalid", () => {
        const classes = classesFor({ invalid: true, runtimeActive: true });
        expect(classes).toContain("border-live");
        expect(classes).not.toContain("border-danger");
    });

    it("only a resting step changes border on hover", () => {
        expect(classesFor({})).toContain("hover:border-ink-3/50");
        expect(classesFor({ invalid: true })).not.toContain("hover:border-ink-3/50");
    });
});
