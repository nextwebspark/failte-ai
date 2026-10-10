import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowProvider } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import type { NodeSpec, SkillSummaryResponse } from "@/client/types.gen";
import type { FlowNode, FlowNodeData } from "@/components/flow/types";

import { GenericNode } from "./GenericNode";

/**
 * Runs the node editor's real save path (form values → handleSaveNodeData →
 * workflow store) and checks the JSON the workflow is saved with, since
 * `skill_uuids` means different things when absent, `[]` or a list.
 */

const mocks = vi.hoisted(() => ({ refreshSkills: vi.fn(async () => {}) }));

vi.mock("@xyflow/react", () => ({
    NodeToolbar: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    Position: { Right: "right" },
}));

vi.mock("./common/NodeContent", () => ({
    NodeContent: ({ children, onDoubleClick }: { children: ReactNode; onDoubleClick: () => void }) => (
        <div>
            <button type="button" onClick={onDoubleClick}>
                Open node
            </button>
            {children}
        </div>
    ),
}));

vi.mock("./common/NodeEditDialog", () => ({
    NodeEditDialog: ({ open, children, onSave }: { open: boolean; children: ReactNode; onSave: () => void }) =>
        open ? (
            <div>
                {children}
                <button type="button" onClick={onSave}>
                    Save node
                </button>
            </div>
        ) : null,
}));

const SPEC = {
    name: "agentNode",
    display_name: "Agent",
    description: "",
    category: "call_node",
    icon: "Bot",
    properties: [
        { name: "prompt", type: "string", display_name: "Prompt", required: false },
        { name: "skill_uuids", type: "skill_refs", display_name: "Skills", required: false },
        { name: "preload_skill_uuids", type: "skill_refs", display_name: "Preloaded Skills", required: false },
    ],
} as unknown as NodeSpec;

vi.mock("@/components/flow/renderer", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/components/flow/renderer")>()),
    useNodeSpecs: () => ({ specs: [SPEC], bySpecName: new Map([["agentNode", SPEC]]) }),
}));

vi.mock("@/context/AppConfigContext", () => ({ useAppConfig: () => ({ config: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.stubGlobal(
    "ResizeObserver",
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

function skill(uuid: string, name: string): SkillSummaryResponse {
    return {
        skill_uuid: uuid,
        name,
        description: name,
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

function renderNode(data: FlowNodeData) {
    const node = { id: "n1", type: "agentNode", position: { x: 0, y: 0 }, data } as FlowNode;
    useWorkflowStore.setState({ nodes: [node] });
    const props = { id: "n1", type: "agentNode", data, selected: false } as unknown as Parameters<typeof GenericNode>[0];
    render(
        <WorkflowProvider
            value={{ saveWorkflow: async () => {}, skills: SKILLS, refreshSkills: mocks.refreshSkills }}
        >
            <GenericNode {...props} />
        </WorkflowProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open node" }));
}

/** The node data exactly as it would be serialized for saving. */
async function savedJson(): Promise<Record<string, unknown>> {
    fireEvent.click(screen.getByRole("button", { name: "Save node" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Save node" })).toBeNull());
    const node = useWorkflowStore.getState().nodes.find((n) => n.id === "n1");
    return JSON.parse(JSON.stringify(node?.data)) as Record<string, unknown>;
}

beforeEach(() => {
    vi.clearAllMocks();
});

describe("GenericNode skill_uuids persistence", () => {
    it("drops the key for 'All skills' so the server sees null", async () => {
        renderNode({ name: "Support", prompt: "Help", skill_uuids: ["s-1"] } as FlowNodeData);
        fireEvent.click(screen.getByRole("radio", { name: /All skills/ }));
        const saved = await savedJson();
        expect("skill_uuids" in saved).toBe(false);
    });

    it("keeps [] for 'None'", async () => {
        renderNode({ name: "Support", prompt: "Help" } as FlowNodeData);
        fireEvent.click(screen.getByRole("radio", { name: /None/ }));
        expect((await savedJson()).skill_uuids).toEqual([]);
    });

    it("keeps the picked list for 'Selected skills', and preloads alongside", async () => {
        renderNode({ name: "Support", prompt: "Help" } as FlowNodeData);
        fireEvent.click(screen.getByRole("radio", { name: /Selected skills/ }));
        fireEvent.click(screen.getAllByRole("checkbox", { name: /booking/ })[0]);
        const preload = screen.getByRole("group", { name: "Preloaded Skills" });
        fireEvent.click(preload.querySelector('[role="checkbox"]') as HTMLElement);
        const saved = await savedJson();
        expect(saved.skill_uuids).toEqual(["s-2"]);
        expect(saved.preload_skill_uuids).toEqual(["s-1"]);
    });

    it("refreshes the skills list when the editor opens", () => {
        renderNode({ name: "Support", prompt: "Help" } as FlowNodeData);
        expect(mocks.refreshSkills).toHaveBeenCalled();
    });
});
