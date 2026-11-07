"use client";

import { Lightbulb, Loader2, MessageSquareText, Mic, Phone, RefreshCw, X } from "lucide-react";
import posthog from "posthog-js";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { createWorkflowRunApiV1WorkflowWorkflowIdRunsPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PostHogEvent } from "@/constants/posthog-events";
import { WORKFLOW_RUN_MODES } from "@/constants/workflowRunModes";
import { useOnboarding } from "@/context/OnboardingContext";
import { useAuth } from "@/lib/auth";
import { cn, getRandomId } from "@/lib/utils";

import { AiSimulatorPlaceholder } from "./workflow-tester/AiSimulatorPlaceholder";
import { EmbeddedVoiceTester } from "./workflow-tester/EmbeddedVoiceTester";
import { ManualTextChatPanel } from "./workflow-tester/ManualTextChatPanel";
import { ChatModeToggle, DisabledNotice, EmptyState } from "./workflow-tester/shared";
import type { WorkflowRuntimeNodeTransition } from "./workflow-tester/types";
import { extractSdkErrorMessage, getErrorMessage } from "./workflow-tester/utils";

interface WorkflowTesterPanelProps {
    workflowId: number;
    initialContextVariables?: Record<string, string>;
    disabled: boolean;
    disabledReason: string | null;
    showWebCallOnboarding?: boolean;
    isVisible?: boolean;
    className?: string;
    onClose?: () => void;
    onRuntimeNodeTransition?: (transition: WorkflowRuntimeNodeTransition) => void;
}

/** "LIVE 00:42" while a browser call is connected. */
function LiveTimer({ since }: { since: number }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);
    const seconds = Math.max(0, Math.floor((now - since) / 1000));
    const clock = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    return (
        <StatusPill tone="live" dot role="status" aria-label={`Call live for ${clock}`}>
            Live <span className="tabular-nums">{clock}</span>
        </StatusPill>
    );
}

export function WorkflowTesterPanel({
    workflowId,
    initialContextVariables,
    disabled,
    disabledReason,
    showWebCallOnboarding = false,
    isVisible = true,
    className,
    onClose,
    onRuntimeNodeTransition,
}: WorkflowTesterPanelProps) {
    const auth = useAuth();
    const { markActionCompleted, hasSeenTooltip, markTooltipSeen } = useOnboarding();
    const { isAuthenticated, loading: authLoading, getAccessToken } = auth;
    const [accessToken, setAccessToken] = useState<string | null>(null);
    const [activeMode, setActiveMode] = useState<"audio" | "text">("audio");
    const [chatMode, setChatMode] = useState<"manual" | "simulated">("manual");
    const [chatSessionKey, setChatSessionKey] = useState(0);
    const [chatActive, setChatActive] = useState(false);
    const [voiceRunId, setVoiceRunId] = useState<number | null>(null);
    const [creatingVoiceRun, setCreatingVoiceRun] = useState(false);
    const [tokenReady, setTokenReady] = useState(false);
    // When the browser call connected, for the LIVE pill; null when no call is live.
    const [liveSince, setLiveSince] = useState<number | null>(null);
    const handleLiveChange = useCallback((live: boolean) => {
        setLiveSince((current) => (live ? (current ?? Date.now()) : null));
    }, []);

    useEffect(() => {
        let ignore = false;

        const hydrateAccessToken = async () => {
            if (!isAuthenticated || authLoading) return;
            try {
                const token = await getAccessToken();
                if (!ignore) {
                    setAccessToken(token);
                }
            } catch (error) {
                if (!ignore) {
                    toast.error(getErrorMessage(error));
                }
            } finally {
                if (!ignore) {
                    setTokenReady(true);
                }
            }
        };

        if (authLoading) {
            return;
        }

        if (!isAuthenticated) {
            setTokenReady(true);
            return;
        }

        hydrateAccessToken();

        return () => {
            ignore = true;
        };
    }, [authLoading, getAccessToken, isAuthenticated]);

    const createVoiceRun = useCallback(async () => {
        if (!accessToken || disabled) return;
        setCreatingVoiceRun(true);
        try {
            const response = await createWorkflowRunApiV1WorkflowWorkflowIdRunsPost({
                path: { workflow_id: workflowId },
                body: {
                    mode: WORKFLOW_RUN_MODES.SMALL_WEBRTC,
                    name: `WR-${getRandomId()}`,
                },
            });

            if (response.error || !response.data?.id) {
                throw new Error(extractSdkErrorMessage(response.error, "Failed to create browser test run"));
            }

            markActionCompleted("web_call_started");
            posthog.capture(PostHogEvent.WEB_CALL_INITIATED, {
                workflow_id: workflowId,
                workflow_run_id: response.data.id,
                source: "workflow_editor",
            });
            setVoiceRunId(response.data.id);
            setActiveMode("audio");
        } catch (error) {
            toast.error(getErrorMessage(error));
        } finally {
            setCreatingVoiceRun(false);
        }
    }, [accessToken, disabled, markActionCompleted, workflowId]);

    const authUnavailableReason = tokenReady && !accessToken
        ? "Authentication is required before testing can start."
        : null;
    const effectiveDisabledReason = disabledReason ?? authUnavailableReason;
    const testerBlocked = disabled || authUnavailableReason !== null;
    const showFirstCallTip =
        showWebCallOnboarding &&
        !hasSeenTooltip("web_call") &&
        isVisible &&
        activeMode === "audio" &&
        !voiceRunId &&
        tokenReady &&
        !!accessToken &&
        !testerBlocked;

    const handleModeChange = (value: string) => {
        const mode = value as "audio" | "text";
        setActiveMode(mode);
        if (mode !== "audio") {
            // Leaving this tab unmounts EmbeddedVoiceTester, whose cleanup closes
            // the socket and peer connection — the call is over at that point and
            // the backend completes the run. A run may only be called once, so
            // release the id here; coming back mints a fresh one rather than
            // re-offering a finished run.
            setVoiceRunId(null);
        }
    };

    return (
        <div className={cn("flex h-full min-h-0 flex-col bg-background", className)}>
            <Tabs
                value={activeMode}
                onValueChange={handleModeChange}
                className="min-h-0 flex-1 gap-0"
            >
                <div className="flex items-center gap-2.5 border-b border-line-soft px-3.5 py-3">
                    <h2 className="text-sm font-semibold text-foreground">Test agent</h2>
                    {liveSince !== null && <LiveTimer since={liveSince} />}
                    <TabsList
                        aria-label="Test with"
                        className="ml-auto h-8 rounded-md border border-line bg-panel-2 p-0.5"
                    >
                        <TabsTrigger value="audio" className="h-full gap-1.5 rounded-sm px-2.5 text-xs">
                            <Mic className="h-3 w-3" />
                            Voice
                        </TabsTrigger>
                        <TabsTrigger value="text" className="h-full gap-1.5 rounded-sm px-2.5 text-xs">
                            <MessageSquareText className="h-3 w-3" />
                            Text
                        </TabsTrigger>
                    </TabsList>
                    {onClose ? (
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={onClose}
                            className="size-8 shrink-0 text-ink-3 hover:text-foreground"
                            aria-label="Close tester panel"
                        >
                            <X className="h-4 w-4" />
                        </Button>
                    ) : null}
                </div>

                <TabsContent value="audio" className="min-h-0 flex-1 px-4 py-4">
                    <div className="flex h-full min-h-0 flex-col gap-3">
                        {!tokenReady ? (
                            <div className="space-y-4">
                                <Skeleton className="h-14 rounded-xl" />
                                <Skeleton className="h-80 rounded-xl" />
                            </div>
                        ) : !accessToken ? (
                            <DisabledNotice
                                reason={authUnavailableReason ?? "Authentication is required before browser tests can start."}
                            />
                        ) : voiceRunId ? (
                            <EmbeddedVoiceTester
                                workflowId={workflowId}
                                workflowRunId={voiceRunId}
                                initialContextVariables={initialContextVariables}
                                accessToken={accessToken}
                                onReset={() => setVoiceRunId(null)}
                                onNodeTransition={onRuntimeNodeTransition}
                                onLiveChange={handleLiveChange}
                            />
                        ) : (
                            <>
                                {effectiveDisabledReason ? <DisabledNotice reason={effectiveDisabledReason} /> : null}
                                <EmptyState
                                    icon={<Phone className="h-5 w-5" />}
                                    title="Talk to your agent"
                                    description="Have a conversation through your computer's microphone, just like a caller would. Putting a caller through to a person only works on a real phone call."
                                    action={
                                        <div className="flex flex-col items-start gap-3">
                                            {/* First-run tip sits inline above the button it
                                                points at, so it never covers the button or the
                                                page beside the panel. */}
                                            {showFirstCallTip && (
                                                <div
                                                    role="note"
                                                    className="flex w-full items-start gap-2.5 rounded-lg border border-brand/30 bg-brand-dim px-3 py-2.5 text-caption text-ink-2"
                                                >
                                                    <Lightbulb className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
                                                    <p className="min-w-0 flex-1 leading-snug">
                                                        <span className="font-semibold text-foreground">New here?</span>{" "}
                                                        Start a test call to hear how your agent answers. Nobody else is called.
                                                    </p>
                                                    <button
                                                        type="button"
                                                        onClick={() => markTooltipSeen("web_call")}
                                                        aria-label="Hide this tip"
                                                        className="-m-1 grid size-7 shrink-0 place-items-center rounded-md text-ink-3 transition-colors hover:bg-panel hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring motion-reduce:transition-none"
                                                    >
                                                        <X className="size-4" aria-hidden />
                                                    </button>
                                                </div>
                                            )}
                                            <Button
                                                size="lg"
                                                data-test-call-start
                                                onClick={() => {
                                                    markTooltipSeen("web_call");
                                                    void createVoiceRun();
                                                }}
                                                disabled={creatingVoiceRun || testerBlocked}
                                            >
                                                {creatingVoiceRun ? (
                                                    <>
                                                        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                                                        Starting the call…
                                                    </>
                                                ) : (
                                                    <>
                                                        <Phone className="h-4 w-4" />
                                                        Start a test call
                                                    </>
                                                )}
                                            </Button>
                                        </div>
                                    }
                                />
                            </>
                        )}
                    </div>
                </TabsContent>

                <TabsContent value="text" className="min-h-0 flex-1 px-4 py-3">
                    <div className="flex h-full min-h-0 flex-col gap-3">
                        <div className="flex items-center justify-between gap-2">
                            <ChatModeToggle value={chatMode} onChange={setChatMode} />
                            {chatMode === "manual" && chatActive ? (
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setChatSessionKey((value) => value + 1)}
                                    disabled={testerBlocked}
                                    className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                                >
                                    <RefreshCw className="h-3.5 w-3.5" />
                                    Reset
                                </Button>
                            ) : null}
                        </div>

                        {chatMode === "manual" ? (
                            <ManualTextChatPanel
                                key={chatSessionKey}
                                workflowId={workflowId}
                                ready={tokenReady && !!accessToken}
                                initialContextVariables={initialContextVariables}
                                disabled={testerBlocked}
                                disabledReason={effectiveDisabledReason}
                                onActiveChange={setChatActive}
                                onNodeTransition={onRuntimeNodeTransition}
                            />
                        ) : (
                            <AiSimulatorPlaceholder disabledReason={effectiveDisabledReason} />
                        )}
                    </div>
                </TabsContent>
            </Tabs>

        </div>
    );
}
