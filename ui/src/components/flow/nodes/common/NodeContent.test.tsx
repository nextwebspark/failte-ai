import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { NodeContent } from "./NodeContent";

vi.mock("@xyflow/react", () => ({
    Handle: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
    Position: { Top: "top", Bottom: "bottom" },
}));

function renderNode(props: Partial<Parameters<typeof NodeContent>[0]> = {}) {
    return render(
        <NodeContent selected={false} title="Book appointment" icon={<svg />} tone="sky" kindLabel="Agent" {...props}>
            <p>Offer the next three slots.</p>
        </NodeContent>,
    );
}

describe("NodeContent", () => {
    it("shows the step's name, kind and preview", () => {
        renderNode();
        expect(screen.getByRole("heading", { name: "Book appointment" })).toBeTruthy();
        expect(screen.getByText("Agent")).toBeTruthy();
        expect(screen.getByText("Offer the next three slots.")).toBeTruthy();
    });

    it("marks the step the live call is on", () => {
        renderNode({ runtimeActive: true, invalid: true });
        expect(screen.getByText("On")).toBeTruthy();
        expect(screen.queryByText("Agent")).toBeNull();
    });

    it("says what to fix on an invalid step", () => {
        renderNode({ invalid: true, invalidMessage: "Add a prompt so the agent knows what to say." });
        expect(screen.getByText("Needs a fix")).toBeTruthy();
        expect(screen.getByText("Add a prompt so the agent knows what to say.")).toBeTruthy();
    });
});
