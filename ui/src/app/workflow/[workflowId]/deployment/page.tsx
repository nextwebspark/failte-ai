"use client";

import { AppWindow } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

import { AgentSectionShell } from "../components/AgentSectionShell";
import { EmbedDialog } from "../components/EmbedDialog";
import { AgentPhoneNumbers } from "./AgentPhoneNumbers";

/**
 * "Deployment" — the canvas's Connect section: how callers reach this agent
 * (app-doc/claude-design/Failte AI v2.dc.html). A phone number first, since
 * most agents answer the phone, then the website widget.
 */
/**
 * The sections render once the agent has loaded, after the browser has
 * already tried to follow a #phone / #website link, so scroll to it then.
 */
function ScrollToHash() {
    useEffect(() => {
        const id = window.location.hash.slice(1);
        if (id) document.getElementById(id)?.scrollIntoView({ block: "start" });
    }, []);
    return null;
}

export default function AgentDeploymentPage() {
    const [isEmbedDialogOpen, setIsEmbedDialogOpen] = useState(false);

    return (
        <AgentSectionShell>
            {({
                workflowId,
                workflowName,
                workflowConfigurations,
                textChatInactivityTimeoutConstraints,
                widgetTextDefaults,
                saveWorkflowConfigurations,
            }) => (
                <div className="page-body max-w-4xl space-y-6">
                    <AgentPhoneNumbers agentId={workflowId} agentName={workflowName} />

                    <section
                        id="website"
                        aria-labelledby="website-title"
                        className="scroll-mt-6 rounded-lg border border-line bg-card"
                    >
                        <header className="border-b border-line-soft px-5 py-4">
                            <h2 id="website-title" className="flex items-center gap-2 text-[15px] font-semibold text-ink">
                                <AppWindow className="size-4 text-ink-3" aria-hidden />
                                Website
                            </h2>
                            <p className="mt-1 text-[13px] text-ink-2">
                                A call button on your website that connects visitors to {workflowName}. Publish
                                the agent after any change so callers get the new version.
                            </p>
                        </header>
                        <div className="px-5 py-4">
                            <Button variant="outline" size="sm" onClick={() => setIsEmbedDialogOpen(true)}>
                                Set up the website widget
                            </Button>
                        </div>
                    </section>

                    <ScrollToHash />
                    <EmbedDialog
                        open={isEmbedDialogOpen}
                        onOpenChange={setIsEmbedDialogOpen}
                        workflowId={workflowId}
                        workflowName={workflowName}
                        workflowConfigurations={workflowConfigurations}
                        textChatInactivityTimeoutConstraints={textChatInactivityTimeoutConstraints}
                        widgetTextDefaults={widgetTextDefaults}
                        onSaveWorkflowConfigurations={saveWorkflowConfigurations}
                    />
                </div>
            )}
        </AgentSectionShell>
    );
}
