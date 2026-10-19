import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const flow = vi.hoisted(() => ({ zoomIn: vi.fn(), zoomOut: vi.fn(), fitView: vi.fn() }));
vi.mock("@xyflow/react", () => ({
    Panel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    useReactFlow: () => flow,
    useViewport: () => ({ x: 0, y: 0, zoom: 0.75 }),
}));

import { CanvasToolbar } from "./CanvasToolbar";

function renderToolbar(overrides: Partial<Parameters<typeof CanvasToolbar>[0]> = {}) {
    const props = {
        readOnly: false,
        onAddNode: vi.fn(),
        onTidy: vi.fn(),
        onUndo: vi.fn(),
        onRedo: vi.fn(),
        canUndo: true,
        canRedo: false,
        ...overrides,
    };
    render(<CanvasToolbar {...props} />);
    return props;
}

describe("CanvasToolbar", () => {
    it("adds a step, drives the view and undoes", () => {
        const props = renderToolbar();

        expect(screen.getByText("75%")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Add step" }));
        fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
        fireEvent.click(screen.getByRole("button", { name: "Fit to view" }));
        fireEvent.click(screen.getByRole("button", { name: "Tidy layout" }));
        fireEvent.click(screen.getByRole("button", { name: "Undo" }));

        expect(props.onAddNode).toHaveBeenCalled();
        expect(flow.zoomIn).toHaveBeenCalled();
        expect(flow.fitView).toHaveBeenCalled();
        expect(props.onTidy).toHaveBeenCalled();
        expect(props.onUndo).toHaveBeenCalled();
        expect(screen.getByRole("button", { name: "Redo" })).toHaveProperty("disabled", true);
    });

    it("keeps only the view controls on an old version", () => {
        renderToolbar({ readOnly: true });

        expect(screen.queryByRole("button", { name: "Add step" })).toBeNull();
        expect(screen.queryByRole("button", { name: "Tidy layout" })).toBeNull();
        expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
        expect(screen.getByRole("button", { name: "Zoom out" })).toBeTruthy();
    });
});
