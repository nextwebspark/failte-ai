import { describe, expect, it, vi } from "vitest";

import type { NodeSpec } from "@/client/types.gen";
import type { FlowNodeData } from "@/components/flow/types";

vi.mock("@/app/workflow/[workflowId]/contexts/WorkflowContext", () => ({ useWorkflow: () => ({}) }));
vi.mock("@/context/AppConfigContext", () => ({ useAppConfig: () => ({ config: null }) }));

const { getKindForSpec } = await import("./GenericNode");

const spec = { name: "agentNode", display_name: "Agent", properties: [] } as unknown as NodeSpec;
const data = (tools: string[] = []) => ({ name: "Step", tool_uuids: tools }) as FlowNodeData;

describe("getKindForSpec", () => {
    it("is brand when the agent only speaks and sky when it uses a tool", () => {
        expect(getKindForSpec(spec, "agent", data())).toEqual({ label: "Agent", tone: "brand" });
        expect(getKindForSpec(spec, "agent", data(["t1"]))).toEqual({ label: "Agent", tone: "sky" });
        expect(getKindForSpec(spec, "start", data(["t1"])).tone).toBe("sky");
    });

    it("marks the end, global instructions and unknown steps", () => {
        expect(getKindForSpec(spec, "end", data())).toEqual({ label: "End", tone: "danger" });
        expect(getKindForSpec(spec, "global", data())).toEqual({ label: "Global", tone: "amber" });
        expect(getKindForSpec(undefined, "agent", data())).toEqual({ label: "Step", tone: "mute" });
    });
});
