"use client";

import { WorkflowTesterPanel } from "@/app/workflow/[workflowId]/components/WorkflowTesterPanel";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

/**
 * "Try your agent" on Home: the agent screen's Test agent panel (Voice /
 * Text) in a side panel, so the owner tries the agent without leaving Home
 * or swapping the sidebar to the agent's own menu.
 *
 * Closing the sheet unmounts the panel, and the voice tester's cleanup ends
 * the call and releases the microphone.
 */
export function HomeTestSheet({
    workflowId,
    agentName,
    open,
    onOpenChange,
}: {
    workflowId: number;
    agentName: string | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}) {
    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            {/* Full width on a phone. The sheet's own X is hidden: the panel
                has its close button beside Voice / Text. */}
            <SheetContent
                side="right"
                className="w-full max-w-none gap-0 p-0 sm:w-[70%] sm:max-w-[560px] [&>button:last-child]:hidden"
            >
                <SheetTitle className="sr-only">Try your agent</SheetTitle>
                <SheetDescription className="sr-only">
                    {agentName ? `Talk to ${agentName} in your browser.` : "Talk to your agent in your browser."} Nobody
                    else is called.
                </SheetDescription>
                {open && (
                    <WorkflowTesterPanel
                        workflowId={workflowId}
                        disabled={false}
                        disabledReason={null}
                        isVisible={open}
                        onClose={() => onOpenChange(false)}
                    />
                )}
            </SheetContent>
        </Sheet>
    );
}
