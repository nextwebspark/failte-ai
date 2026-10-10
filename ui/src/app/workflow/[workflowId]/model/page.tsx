"use client";

import { AgentSectionShell } from "../components/AgentSectionShell";
import { WorkflowModelOverridesSection } from "./WorkflowModelOverridesSection";

/**
 * "Model and voice" — the canvas's Configure section for the stack this agent
 * speaks with (app-doc/claude-design/Failte AI v2.dc.html). The workspace-wide
 * stack lives at /model-configurations; this screen is where one agent departs
 * from it.
 */
export default function AgentModelAndVoicePage() {
    return (
        <AgentSectionShell>
            {({ workflowConfigurations, workflowName, saveWorkflowConfigurations }) => (
                <div className="page-body max-w-4xl space-y-6">
                    <WorkflowModelOverridesSection
                        workflowConfigurations={workflowConfigurations}
                        workflowName={workflowName}
                        onSave={saveWorkflowConfigurations}
                    />
                </div>
            )}
        </AgentSectionShell>
    );
}
