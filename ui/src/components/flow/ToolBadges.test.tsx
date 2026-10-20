import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkflowProvider } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import type { ToolResponse } from "@/client/types.gen";

import { ToolBadges } from "./ToolBadges";

function tool(uuid: string, name: string, category = "http_api"): ToolResponse {
    return { tool_uuid: uuid, name, category } as unknown as ToolResponse;
}

function renderBadges(props: Parameters<typeof ToolBadges>[0], tools: ToolResponse[]) {
    return render(
        <WorkflowProvider value={{ saveWorkflow: async () => {}, tools }}>
            <ToolBadges {...props} />
        </WorkflowProvider>,
    );
}

describe("ToolBadges", () => {
    it("shows one chip per tool, and an MCP server's enabled functions", () => {
        renderBadges(
            { toolUuids: ["t1", "m1"], mcpToolFilters: { m1: ["free_slots", "book"] } },
            [tool("t1", "find_patient"), tool("m1", "Google Calendar", "mcp")],
        );
        expect(screen.getByText("find_patient")).toBeTruthy();
        expect(screen.getByText("free_slots")).toBeTruthy();
        expect(screen.getByText("book")).toBeTruthy();
        expect(screen.queryByText("Google Calendar")).toBeNull();
    });

    it("falls back to the server's name when no functions are picked", () => {
        renderBadges({ toolUuids: ["m1"] }, [tool("m1", "Google Calendar", "mcp")]);
        expect(screen.getByText("Google Calendar")).toBeTruthy();
    });

    it("collapses chips past three into +N more", () => {
        const tools = ["a", "b", "c", "d", "e"].map((n) => tool(n, `tool_${n}`));
        renderBadges({ toolUuids: tools.map((t) => t.tool_uuid) }, tools);
        expect(screen.getByText("tool_c")).toBeTruthy();
        expect(screen.queryByText("tool_d")).toBeNull();
        expect(screen.getByText("+2 more").getAttribute("title")).toBe("tool_d, tool_e");
    });

    it("reports tools that no longer exist", () => {
        const onStale = vi.fn();
        renderBadges({ toolUuids: ["t1", "gone"], onStaleUuidsDetected: onStale }, [tool("t1", "find_patient")]);
        expect(onStale).toHaveBeenCalledWith(["gone"]);
    });
});
