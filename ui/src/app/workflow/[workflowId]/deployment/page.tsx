"use client";

import { ExternalLink, Rocket } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

import { AgentSectionShell } from "../components/AgentSectionShell";
import { EmbedDialog } from "../components/EmbedDialog";

/**
 * "Deployment" — the canvas's Connect section: where this agent goes live
 * (app-doc/claude-design/Failte AI v2.dc.html). Today that is the website
 * widget; telephony numbers are still attached at the workspace level.
 */
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
                    <Card id="deployment">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2 text-base">
                                <Rocket className="h-4 w-4" />
                                Add to website
                            </CardTitle>
                            <CardDescription>
                                Configure a widget that puts this voice agent on your website. Publish
                                the agent after any change so callers get the new version.
                            </CardDescription>
                        </CardHeader>
                        <CardFooter className="border-t pt-6">
                            <Button variant="outline" onClick={() => setIsEmbedDialogOpen(true)}>
                                Configure widget
                            </Button>
                        </CardFooter>
                    </Card>

                    <Card>
                        <CardHeader>
                            <CardTitle className="text-base">Phone numbers</CardTitle>
                            <CardDescription>
                                Inbound numbers and SIP trunks are shared across the workspace and
                                pointed at an agent from the telephony screen.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <Button variant="outline" asChild>
                                <Link href="/telephony-configurations">
                                    Go to telephony
                                    <ExternalLink className="ml-2 h-4 w-4" />
                                </Link>
                            </Button>
                        </CardContent>
                    </Card>

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
