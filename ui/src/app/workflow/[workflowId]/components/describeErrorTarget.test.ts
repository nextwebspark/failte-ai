import { describe, expect, it } from "vitest";

import { describeErrorTarget } from "./WorkflowEditorHeader";

const flow = {
    getNode: (id: string) =>
        ({ "3": { data: { name: "Identify caller" } }, "5": { data: { name: "Book appointment" } } })[id],
    getEdge: (id: string) => (id === "3-5" ? { source: "3", target: "5" } : undefined),
} as unknown as Parameters<typeof describeErrorTarget>[1];

describe("describeErrorTarget", () => {
    it("names a step instead of its id", () => {
        expect(describeErrorTarget({ kind: "node", id: "3", field: null, message: "" }, flow)).toBe(
            "Step: Identify caller",
        );
    });

    it("names both ends of a connection", () => {
        expect(describeErrorTarget({ kind: "edge", id: "3-5", field: null, message: "" }, flow)).toBe(
            "Connection: Identify caller → Book appointment",
        );
    });

    it("falls back to the id when the canvas can't find it", () => {
        expect(describeErrorTarget({ kind: "edge", id: "9-9", field: null, message: "" }, flow)).toBe(
            "Connection: 9-9",
        );
        expect(describeErrorTarget({ kind: "node", id: "7", field: null, message: "" }, null)).toBe("Step: 7");
    });
});
