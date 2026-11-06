'use client';

import {
    ArrowLeft,
    Bot,
    Check,
    ChevronDown,
    Clock,
    Copy,
    Download,
    ExternalLink,
    FileText,
    Loader2,
    Pause,
    Play,
    UserRound,
} from 'lucide-react';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import posthog from 'posthog-js';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { formatCallTime, outcomeLabel } from '@/app/usage/callsView';
import {
    getWorkflowApiV1WorkflowFetchWorkflowIdGet,
    getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet,
} from '@/client/sdk.gen';
import { agentSectionFor, isAgentRoute } from '@/components/layout/agentNav';
import { getPageMeta } from '@/components/layout/navConfig';
import { RETURN_TO_PARAM, safeReturnTo } from '@/components/layout/shellContext';
import { MediaPreviewButton, MediaPreviewDialog } from '@/components/MediaPreviewDialog';
import { OnboardingTooltip } from '@/components/onboarding/OnboardingTooltip';
import { DeleteCallDataButton } from '@/components/privacy/DeleteCallDataButton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ConversationRailFrame, RealtimeFeedback, WorkflowRunLogs } from '@/components/workflow/conversation';
import { conversationItemsFromRealtimeFeedbackEvents } from '@/components/workflow/conversation/adapters/fromRealtimeFeedback';
import { PostHogEvent } from '@/constants/posthog-events';
import { WORKFLOW_RUN_MODES } from '@/constants/workflowRunModes';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { useIsMobile } from '@/hooks/use-mobile';
import { useOrganizationTimezone } from '@/hooks/useOrganizationTimezone';
import { useAuth } from '@/lib/auth';
import { copyTextToClipboard } from '@/lib/clipboard';
import { downloadFile, getSignedUrl } from '@/lib/files';
import { cn } from '@/lib/utils';

import { SkillsLoadedSection } from './SkillsLoadedSection';

interface WorkflowRunResponse {
    mode: string;
    created_at: string | null;
    is_completed: boolean;
    transcript_url: string | null;
    recording_url: string | null;
    user_recording_url: string | null;
    bot_recording_url: string | null;
    cost_info: {
        dograh_token_usage?: number | null;
        call_duration_seconds?: number | null;
    } | null;
    initial_context: Record<string, string | number | boolean | object> | null;
    gathered_context: Record<string, string | number | boolean | object> | null;
    logs: WorkflowRunLogs | null;
    annotations: Record<string, unknown> | null;
}

const WAVEFORM_BAR_COUNT = 96;
type SplitTrackPlaybackMode = 'both' | 'user' | 'bot';

function formatDuration(seconds?: number | null) {
    if (seconds == null || Number.isNaN(seconds)) return 'Not known';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins === 0) return `${secs}s`;
    return `${mins}m ${secs}s`;
}

/** A plain string from a run's context, or null. */
function contextString(context: Record<string, unknown> | null | undefined, key: string): string | null {
    const value = context?.[key];
    return typeof value === 'string' && value.trim() ? value : null;
}

function getTranscriptMetrics(logs: WorkflowRunLogs | null, gatheredContext: Record<string, string | number | boolean | object> | null) {
    const events = logs?.realtime_feedback_events ?? [];
    const userTurns = events.filter((event) => event.type === 'rtf-user-transcription' && event.payload.final).length;
    const botTurns = events.filter((event) => event.type === 'rtf-bot-text').length;
    const toolCalls = conversationItemsFromRealtimeFeedbackEvents(events, gatheredContext?.tool_results)
        .filter((item) => item.kind === 'tool-call' && item.status !== 'running').length;
    const nodeNames = new Set(
        events
            .map((event) => event.payload.node_name)
            .filter((nodeName): nodeName is string => Boolean(nodeName))
    );
    const visitedNodes = Array.isArray(gatheredContext?.nodes_visited)
        ? gatheredContext.nodes_visited.length
        : nodeNames.size;

    return { userTurns, botTurns, toolCalls, visitedNodes };
}

function MetricCard({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-xl border border-border bg-muted/40 px-4 py-3">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
            <p className="mt-2 text-lg font-semibold text-foreground">{value}</p>
        </div>
    );
}

function CopyDebugIdButton({ label, value }: { label: string; value: string }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        try {
            await copyTextToClipboard(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            toast.error(`Failed to copy ${label}`);
        }
    };

    // One flat chip on the run bar — the old two-line card ate a whole column.
    return (
        <button
            type="button"
            onClick={handleCopy}
            aria-label={`Copy ${label.toLowerCase()}`}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/30 px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
        >
            <span className="text-[10px] font-medium uppercase tracking-[0.12em]">{label}</span>
            <span className="font-mono text-xs font-semibold text-foreground">{value}</span>
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3 opacity-60" />}
        </button>
    );
}

function buildWaveformPeaks(audioBuffer: AudioBuffer) {
    const channel = audioBuffer.getChannelData(0);
    const samplesPerBar = Math.max(1, Math.floor(channel.length / WAVEFORM_BAR_COUNT));

    return Array.from({ length: WAVEFORM_BAR_COUNT }, (_, index) => {
        const start = index * samplesPerBar;
        const end = Math.min(start + samplesPerBar, channel.length);
        let sum = 0;

        for (let i = start; i < end; i += 1) {
            sum += channel[i] * channel[i];
        }

        const rms = Math.sqrt(sum / Math.max(1, end - start));
        return Math.max(0.08, Math.min(1, rms * 5));
    });
}

async function loadWaveformPeaks(url: string) {
    const response = await fetch(url);
    const audioData = await response.arrayBuffer();
    const AudioContextConstructor =
        window.AudioContext ||
        (window as typeof window & { webkitAudioContext?: typeof AudioContext })
            .webkitAudioContext;

    if (!AudioContextConstructor) return null;

    const audioContext = new AudioContextConstructor();
    try {
        const decoded = await audioContext.decodeAudioData(audioData);
        return buildWaveformPeaks(decoded);
    } finally {
        void audioContext.close();
    }
}

function getAudioDuration(audio: HTMLAudioElement | null) {
    return audio && Number.isFinite(audio.duration) ? audio.duration : 0;
}

function getAudioTimelineState(audios: HTMLAudioElement[]) {
    const duration = Math.max(0, ...audios.map((audio) => getAudioDuration(audio)));
    const currentTime = Math.max(0, ...audios.map((audio) => audio.currentTime));

    return { duration, currentTime };
}

function syncAudioCurrentTime(audio: HTMLAudioElement, startTime: number) {
    const duration = getAudioDuration(audio);
    audio.currentTime = Math.min(startTime, duration || startTime);
}

function WaveformLane({
    peaks,
    track,
    position,
    isActive,
}: {
    peaks: number[] | null;
    track: 'user' | 'bot';
    position: 'top' | 'bottom';
    isActive: boolean;
}) {
    return (
        <div
            className={cn(
                'absolute left-3 right-3 flex gap-0.5',
                isActive ? 'opacity-85' : 'opacity-25',
                position === 'top' ? 'top-5 h-12 items-end' : 'bottom-5 h-12 items-start'
            )}
        >
            {peaks ? (
                peaks.map((peak, index) => (
                    <span
                        key={`${track}-${index}`}
                        className={cn(
                            'min-h-1 flex-1 rounded-full',
                            track === 'user' ? 'bg-sky' : 'bg-ok'
                        )}
                        style={{ height: `${Math.round(peak * 100)}%` }}
                    />
                ))
            ) : (
                <div className="my-auto h-px w-full bg-border" />
            )}
        </div>
    );
}

function SplitTracksSection({
    userRecordingUrl,
    botRecordingUrl,
}: {
    userRecordingUrl: string;
    botRecordingUrl: string;
}) {
    const userAudioRef = useRef<HTMLAudioElement | null>(null);
    const botAudioRef = useRef<HTMLAudioElement | null>(null);
    const [signedUrls, setSignedUrls] = useState<{ user: string | null; bot: string | null }>({
        user: null,
        bot: null,
    });
    const [peaks, setPeaks] = useState<{ user: number[] | null; bot: number[] | null }>({
        user: null,
        bot: null,
    });
    const [isLoading, setIsLoading] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const [progress, setProgress] = useState(0);
    const [playbackMode, setPlaybackMode] = useState<SplitTrackPlaybackMode>('both');

    const getPlaybackAudios = (mode: SplitTrackPlaybackMode) => {
        const audios: HTMLAudioElement[] = [];

        if (mode !== 'bot' && userAudioRef.current) {
            audios.push(userAudioRef.current);
        }

        if (mode !== 'user' && botAudioRef.current) {
            audios.push(botAudioRef.current);
        }

        return audios;
    };

    useEffect(() => {
        let isActive = true;
        const userAudio = userAudioRef.current;
        const botAudio = botAudioRef.current;

        userAudio?.pause();
        botAudio?.pause();
        setSignedUrls({ user: null, bot: null });
        setPeaks({ user: null, bot: null });
        setIsPlaying(false);
        setProgress(0);
        setPlaybackMode('both');
        setIsLoading(true);

        async function loadTracks() {
            try {
                const [userUrl, botUrl] = await Promise.all([
                    getSignedUrl(userRecordingUrl, true),
                    getSignedUrl(botRecordingUrl, true),
                ]);
                if (!isActive) return;

                setSignedUrls({ user: userUrl, bot: botUrl });
                if (!userUrl || !botUrl) return;

                const [userPeaks, botPeaks] = await Promise.all([
                    loadWaveformPeaks(userUrl),
                    loadWaveformPeaks(botUrl),
                ]);

                if (isActive) {
                    setPeaks({ user: userPeaks, bot: botPeaks });
                }
            } catch (error) {
                console.error('Error loading split track waveforms:', error);
            } finally {
                if (isActive) {
                    setIsLoading(false);
                }
            }
        }

        void loadTracks();

        return () => {
            isActive = false;
            userAudio?.pause();
            botAudio?.pause();
        };
    }, [userRecordingUrl, botRecordingUrl]);

    useEffect(() => {
        if (!isPlaying) return;

        let frameId: number;
        const updateProgress = () => {
            const activeAudios: HTMLAudioElement[] = [];

            if (playbackMode !== 'bot' && userAudioRef.current) {
                activeAudios.push(userAudioRef.current);
            }

            if (playbackMode !== 'user' && botAudioRef.current) {
                activeAudios.push(botAudioRef.current);
            }

            const { duration, currentTime } = getAudioTimelineState(activeAudios);

            setProgress(duration > 0 ? Math.min(1, currentTime / duration) : 0);
            frameId = window.requestAnimationFrame(updateProgress);
        };

        frameId = window.requestAnimationFrame(updateProgress);
        return () => window.cancelAnimationFrame(frameId);
    }, [isPlaying, playbackMode]);

    const pauseTracks = () => {
        userAudioRef.current?.pause();
        botAudioRef.current?.pause();
        setIsPlaying(false);
    };

    const handleTrackEnded = () => {
        const activeAudios = getPlaybackAudios(playbackMode);
        const activeTracksDone = activeAudios.length > 0 && activeAudios.every((audio) => audio.ended);

        if (activeTracksDone) {
            setIsPlaying(false);
            setProgress(1);
        }
    };

    const handlePlaybackModeChange = async (nextMode: SplitTrackPlaybackMode) => {
        if (nextMode === playbackMode) return;

        const { currentTime } = getAudioTimelineState(getPlaybackAudios(playbackMode));
        const nextAudios = getPlaybackAudios(nextMode);
        const { duration } = getAudioTimelineState(nextAudios);
        const startTime = duration > 0 && currentTime >= duration - 0.1 ? 0 : currentTime;

        userAudioRef.current?.pause();
        botAudioRef.current?.pause();
        nextAudios.forEach((audio) => syncAudioCurrentTime(audio, startTime));
        setPlaybackMode(nextMode);
        setProgress(duration > 0 ? Math.min(1, startTime / duration) : 0);

        if (!isPlaying) return;

        if (nextAudios.length === 0) {
            setIsPlaying(false);
            return;
        }

        try {
            await Promise.all(nextAudios.map((audio) => audio.play()));
            setIsPlaying(true);
        } catch (error) {
            pauseTracks();
            console.error('Error switching split track playback:', error);
        }
    };

    const handleTrackButtonClick = (track: 'user' | 'bot') => {
        const nextMode = playbackMode === track ? 'both' : track;
        void handlePlaybackModeChange(nextMode);
    };

    const togglePlayback = async () => {
        const playbackAudios = getPlaybackAudios(playbackMode);
        if (!canPlay || playbackAudios.length === 0) return;

        if (isPlaying) {
            pauseTracks();
            return;
        }

        const { duration, currentTime } = getAudioTimelineState(playbackAudios);
        const startTime = duration > 0 && currentTime >= duration - 0.1 ? 0 : currentTime;

        userAudioRef.current?.pause();
        botAudioRef.current?.pause();
        playbackAudios.forEach((audio) => syncAudioCurrentTime(audio, startTime));

        try {
            await Promise.all(playbackAudios.map((audio) => audio.play()));
            setIsPlaying(true);
        } catch (error) {
            pauseTracks();
            console.error('Error playing split tracks:', error);
        }
    };

    const canPlay =
        playbackMode === 'both'
            ? Boolean(signedUrls.user && signedUrls.bot)
            : playbackMode === 'user'
                ? Boolean(signedUrls.user)
                : Boolean(signedUrls.bot);
    const progressPercent = Math.round(progress * 1000) / 10;
    const userTrackActive = playbackMode !== 'bot';
    const botTrackActive = playbackMode !== 'user';
    const playbackTargetLabel = playbackMode === 'both' ? 'split tracks' : `${playbackMode} track`;

    return (
        <Card className="border-border">
            <audio
                ref={userAudioRef}
                src={signedUrls.user ?? undefined}
                preload="metadata"
                className="hidden"
                onEnded={handleTrackEnded}
            />
            <audio
                ref={botAudioRef}
                src={signedUrls.bot ?? undefined}
                preload="metadata"
                className="hidden"
                onEnded={handleTrackEnded}
            />
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Split Tracks</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2" role="group" aria-label="Playback tracks">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            aria-pressed={userTrackActive}
                            aria-label={playbackMode === 'user' ? 'Play both tracks' : 'Play user track only'}
                            onClick={() => handleTrackButtonClick('user')}
                            // The dark: and hover: twins outrank the outline variant's
                            // dark:bg-input/30, dark:border-input and hover:bg-accent.
                            className={cn(
                                'gap-1.5',
                                userTrackActive
                                    ? 'border-sky/30 bg-sky-dim text-sky hover:bg-sky/15 hover:text-sky dark:border-sky/30 dark:bg-sky-dim dark:hover:bg-sky/15'
                                    : 'text-muted-foreground opacity-60'
                            )}
                        >
                            <UserRound className="h-4 w-4" />
                            User
                        </Button>
                        <span className="h-4 w-px bg-border" />
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            aria-pressed={botTrackActive}
                            aria-label={playbackMode === 'bot' ? 'Play both tracks' : 'Play bot track only'}
                            onClick={() => handleTrackButtonClick('bot')}
                            className={cn(
                                'gap-1.5',
                                botTrackActive
                                    ? 'border-ok/30 bg-ok-dim text-ok hover:bg-ok/15 hover:text-ok dark:border-ok/30 dark:bg-ok-dim dark:hover:bg-ok/15'
                                    : 'text-muted-foreground opacity-60'
                            )}
                        >
                            <Bot className="h-4 w-4" />
                            Bot
                        </Button>
                    </div>
                    <div className="flex items-center gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => downloadFile(userRecordingUrl)}
                            className="gap-2"
                        >
                            <Download className="h-4 w-4" />
                            User
                        </Button>
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => downloadFile(botRecordingUrl)}
                            className="gap-2"
                        >
                            <Download className="h-4 w-4" />
                            Bot
                        </Button>
                    </div>
                </div>
                <div className="flex items-center gap-4">
                    <Button
                        type="button"
                        size="icon"
                        variant={isPlaying ? 'default' : 'outline'}
                        onClick={togglePlayback}
                        disabled={!canPlay}
                        aria-label={isPlaying ? `Pause ${playbackTargetLabel}` : `Play ${playbackTargetLabel}`}
                        className="h-10 w-10 shrink-0"
                    >
                        {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                    </Button>
                    <div className="relative h-36 min-w-0 flex-1 overflow-hidden rounded-lg border border-border/70 bg-background">
                        <div className="absolute left-3 right-3 top-1/2 h-px bg-border/80" />
                        <WaveformLane peaks={peaks.user} track="user" position="top" isActive={userTrackActive} />
                        <WaveformLane peaks={peaks.bot} track="bot" position="bottom" isActive={botTrackActive} />
                        {canPlay && (
                            <div className="pointer-events-none absolute inset-x-3 inset-y-3">
                                <div
                                    className="absolute top-0 bottom-0 w-px bg-foreground/50"
                                    style={{ left: `${progressPercent}%` }}
                                />
                            </div>
                        )}
                        {isLoading && (
                            <div className="absolute inset-0 flex items-center justify-center bg-background/70 text-xs text-muted-foreground">
                                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                                Loading
                            </div>
                        )}
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}

function RunMetricsSection({
    costInfo,
    logs,
    gatheredContext,
}: {
    costInfo: WorkflowRunResponse['cost_info'];
    logs: WorkflowRunLogs | null;
    gatheredContext: Record<string, string | number | boolean | object> | null;
}) {
    const metrics = getTranscriptMetrics(logs, gatheredContext);

    return (
        <Card className="border-border">
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Conversation metrics</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <MetricCard label="Duration" value={formatDuration(costInfo?.call_duration_seconds)} />
                <MetricCard label="User Turns" value={String(metrics.userTurns)} />
                <MetricCard label="Bot Turns" value={String(metrics.botTurns)} />
                <MetricCard label="Tool Calls" value={String(metrics.toolCalls)} />
                <MetricCard label="Nodes Visited" value={String(metrics.visitedNodes)} />
            </CardContent>
        </Card>
    );
}

function ContextDisplay({ title, context }: { title: string; context: Record<string, string | number | boolean | object> | null }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        if (!context) return;
        try {
            await copyTextToClipboard(JSON.stringify(context, null, 2));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            toast.error('Failed to copy context');
        }
    };

    if (!context || Object.keys(context).length === 0) {
        return (
            <Card className="border-border">
                <CardHeader className="pb-2">
                    <CardTitle className="text-lg">{title}</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-sm text-muted-foreground">No data available</p>
                </CardContent>
            </Card>
        );
    }

    return (
        <Card className="border-border">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-lg">{title}</CardTitle>
                <Button variant="ghost" size="sm" onClick={handleCopy} className="gap-2">
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    {copied ? 'Copied' : 'Copy'}
                </Button>
            </CardHeader>
            <CardContent>
                <pre className="text-sm bg-muted p-3 rounded-md overflow-auto max-h-64">
                    {JSON.stringify(context, null, 2)}
                </pre>
            </CardContent>
        </Card>
    );
}


export default function WorkflowRunPage() {
    const params = useParams();
    const [isLoading, setIsLoading] = useState(true);
    const auth = useAuth();
    const organizationTimezone = useOrganizationTimezone();
    const [workflowRun, setWorkflowRun] = useState<WorkflowRunResponse | null>(null);
    const [workflowName, setWorkflowName] = useState<string | null>(null);
    const searchParams = useSearchParams();
    const agentLinkRef = useRef<HTMLAnchorElement | null>(null);
    const { can } = useOrgConfig();
    // The agent-editor tip would cover the call on a phone.
    const isMobile = useIsMobile();
    // Bumped after the call's data is deleted, to show the run as it is now.
    const [reloadKey, setReloadKey] = useState(0);

    // Redirect if not authenticated
    useEffect(() => {
        if (!auth.loading && !auth.isAuthenticated) {
            auth.redirectToLogin();
        }
    }, [auth]);

    const { openPreview, dialog } = MediaPreviewDialog();

    useEffect(() => {
        const fetchWorkflowRun = async () => {
            if (!auth.isAuthenticated || auth.loading) return;

            setIsLoading(true);
            setWorkflowName(null);
            const workflowId = Number(params.workflowId);
            const runId = Number(params.runId);

            try {
                const [runResponse, workflowResponse] = await Promise.all([
                    getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet({
                        path: {
                            workflow_id: workflowId,
                            run_id: runId,
                        },
                    }),
                    getWorkflowApiV1WorkflowFetchWorkflowIdGet({
                        path: {
                            workflow_id: workflowId,
                        },
                    }),
                ]);

                setWorkflowName(workflowResponse.data?.name ?? null);
                const runData = {
                    mode: runResponse.data?.mode ?? '',
                    created_at: runResponse.data?.created_at ?? null,
                    is_completed: runResponse.data?.is_completed ?? false,
                    transcript_url: runResponse.data?.transcript_url ?? null,
                    recording_url: runResponse.data?.recording_url ?? null,
                    user_recording_url: runResponse.data?.user_recording_url ?? null,
                    bot_recording_url: runResponse.data?.bot_recording_url ?? null,
                    cost_info: runResponse.data?.cost_info ?? null,
                    initial_context: runResponse.data?.initial_context as Record<string, string> | null ?? null,
                    gathered_context: runResponse.data?.gathered_context as Record<string, string> | null ?? null,
                    logs: runResponse.data?.logs as WorkflowRunLogs | null ?? null,
                    annotations: runResponse.data?.annotations as Record<string, unknown> | null ?? null,
                };
                setWorkflowRun(runData);
                posthog.capture(PostHogEvent.WORKFLOW_RUN_DETAILS_VIEWED, {
                    workflow_id: workflowId,
                    workflow_name: workflowResponse.data?.name ?? null,
                    run_id: runId,
                    is_completed: runData.is_completed,
                    has_recording: !!runData.recording_url,
                    has_split_recordings: !!runData.user_recording_url && !!runData.bot_recording_url,
                    has_transcript: !!runData.transcript_url,
                });
            } finally {
                setIsLoading(false);
            }
        };
        fetchWorkflowRun();
    }, [params.workflowId, params.runId, auth, reloadKey]);

    let returnValue = null;
    const isTextChatRun = workflowRun?.mode === WORKFLOW_RUN_MODES.TEXTCHAT;
    const showRunDetailsView = Boolean(workflowRun?.is_completed || isTextChatRun);
    const userSplitRecordingUrl = workflowRun?.user_recording_url ?? null;
    const botSplitRecordingUrl = workflowRun?.bot_recording_url ?? null;
    const hasSplitTracks = Boolean(userSplitRecordingUrl && botSplitRecordingUrl);
    const workflowId = String(params.workflowId);
    const runId = String(params.runId);

    // Where this run was opened from decides both the shell (agent nav vs
    // workspace nav — see components/layout/shellContext) and this back link.
    const returnTo = safeReturnTo(searchParams.get(RETURN_TO_PARAM));
    const cameFromWorkspace = returnTo !== null && !isAgentRoute(returnTo);
    const backHref = returnTo ?? `/workflow/${workflowId}/runs`;
    const backLabel = cameFromWorkspace && returnTo
        ? getPageMeta(returnTo).title
        : agentSectionFor(returnTo ?? `/workflow/${workflowId}/runs`)?.title ?? 'Calls';

    if (isLoading) {
        returnValue = (
            <div className="flex h-full items-center justify-center p-6">
                <div className="w-full max-w-4xl">
                    <Card>
                        <CardHeader>
                            <Skeleton className="h-6 w-48" />
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <Skeleton className="h-4 w-full" />
                            <Skeleton className="h-4 w-3/4" />
                            <Skeleton className="h-4 w-1/2" />
                        </CardContent>
                        <CardFooter className="flex gap-4">
                            <Skeleton className="h-10 w-32" />
                            <Skeleton className="h-10 w-32" />
                        </CardFooter>
                    </Card>
                </div>
            </div>
        );
    }
    else if (showRunDetailsView) {
        const callerNumber = contextString(workflowRun?.initial_context, 'caller_number')
            ?? contextString(workflowRun?.initial_context, 'called_number');
        const outcome = contextString(workflowRun?.gathered_context, 'mapped_call_disposition');
        returnValue = (
            // Summary, then the conversation, then the technical detail: in
            // that order on a phone; on wide screens the conversation sits beside.
            <div className="grid min-h-0 w-full gap-6 p-4 sm:p-6 xl:h-full xl:grid-cols-[minmax(0,1fr)_minmax(360px,34%)] xl:grid-rows-[auto_minmax(0,1fr)]">
                <div className="min-w-0 space-y-4 xl:col-start-1 xl:row-start-1">
                    <Link
                        href={backHref}
                        className="inline-flex min-h-10 items-center gap-1.5 rounded-md text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:min-h-0"
                    >
                        <ArrowLeft className="h-4 w-4" aria-hidden />
                        {backLabel}
                    </Link>

                    {/* What an owner wants first: who called, when, how it
                        ended, how long, and the recording. */}
                    <section
                        aria-labelledby="call-title"
                        className="rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel p-5 sm:p-6"
                    >
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                            <span
                                className={cn(
                                    'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
                                    isTextChatRun ? 'bg-sky-dim text-sky' : 'bg-ok-dim text-ok'
                                )}
                            >
                                {isTextChatRun ? <FileText className="h-3.5 w-3.5" aria-hidden /> : <Check className="h-3.5 w-3.5" aria-hidden />}
                                {isTextChatRun ? 'Text chat' : 'Call finished'}
                            </span>
                            {cameFromWorkspace && workflowName && (
                                <Link
                                    ref={agentLinkRef}
                                    href={`/workflow/${workflowId}`}
                                    className="inline-flex min-h-10 min-w-0 items-center gap-1.5 rounded-md border border-line bg-panel px-2 py-1 text-sm text-ink-2 transition-colors sm:min-h-0 hover:border-brand/50 hover:text-brand focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
                                >
                                    <Bot className="h-3.5 w-3.5 shrink-0" aria-hidden />
                                    <span className="truncate">{workflowName}</span>
                                </Link>
                            )}
                        </div>
                        <h2 id="call-title" className="mt-3 font-bold tracking-tight">
                            {callerNumber ? (
                                <>
                                    <span className="block text-sm font-medium text-ink-3">Call from</span>{' '}
                                    <span className="block font-mono text-xl sm:text-[22px]">{callerNumber}</span>
                                </>
                            ) : (
                                <span className="text-[22px]">{`Call #${runId}`}</span>
                            )}
                        </h2>
                        {workflowRun?.created_at && (
                            <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-2">
                                <Clock className="h-4 w-4 text-ink-3" aria-hidden />
                                {formatCallTime(workflowRun.created_at, organizationTimezone)}
                            </p>
                        )}

                        <dl className="mt-4 grid grid-cols-2 gap-3 sm:max-w-md">
                            <div className="rounded-lg border border-line bg-panel px-3 py-2.5">
                                <dt className="text-xs text-ink-3">How it ended</dt>
                                <dd className="mt-0.5 font-semibold">{outcome ? outcomeLabel(outcome) : 'Not recorded'}</dd>
                            </div>
                            <div className="rounded-lg border border-line bg-panel px-3 py-2.5">
                                <dt className="text-xs text-ink-3">Length</dt>
                                <dd className="mt-0.5 font-mono font-semibold tabular-nums">
                                    {formatDuration(workflowRun?.cost_info?.call_duration_seconds)}
                                </dd>
                            </div>
                        </dl>

                        {!isTextChatRun && (
                            <div className="mt-4 flex flex-wrap items-center gap-2 [&_button]:h-10 sm:[&_button]:h-9">
                                {workflowRun?.recording_url || workflowRun?.transcript_url ? (
                                    <span className="inline-flex items-center gap-2 text-sm text-ink-2 [&>button]:w-10 sm:[&>button]:w-9">
                                        <MediaPreviewButton
                                            recordingUrl={workflowRun?.recording_url}
                                            transcriptUrl={workflowRun?.transcript_url}
                                            runId={Number(params.runId)}
                                            onOpenPreview={openPreview}
                                        />
                                        <span aria-hidden>Listen</span>
                                    </span>
                                ) : null}
                                <Button
                                    onClick={() => downloadFile(workflowRun?.recording_url ?? null)}
                                    disabled={!workflowRun?.recording_url || !auth.isAuthenticated}
                                    size="sm"
                                    variant="outline"
                                    className="gap-2 bg-panel"
                                >
                                    <Download className="h-4 w-4" aria-hidden />
                                    Recording
                                </Button>
                                <Button
                                    onClick={() => downloadFile(workflowRun?.transcript_url ?? null)}
                                    disabled={!workflowRun?.transcript_url || !auth.isAuthenticated}
                                    size="sm"
                                    variant="outline"
                                    className="gap-2 bg-panel"
                                >
                                    <Download className="h-4 w-4" aria-hidden />
                                    Transcript
                                </Button>
                                {can('org:manage') && (
                                    <div className="sm:ml-auto">
                                        <DeleteCallDataButton
                                            workflowId={Number(params.workflowId)}
                                            runId={Number(params.runId)}
                                            onDeleted={() => setReloadKey((key) => key + 1)}
                                        />
                                    </div>
                                )}
                            </div>
                        )}
                        {isTextChatRun && can('org:manage') && (
                            <div className="mt-4">
                                <DeleteCallDataButton
                                    workflowId={Number(params.workflowId)}
                                    runId={Number(params.runId)}
                                    onDeleted={() => setReloadKey((key) => key + 1)}
                                />
                            </div>
                        )}
                    </section>
                </div>

                {/* The conversation: beside the details on xl, under the summary below it. */}
                <div className="h-[520px] w-full min-w-0 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:h-full xl:min-h-0">
                    <ConversationRailFrame className="h-full">
                        <RealtimeFeedback
                            mode="historical"
                            logs={workflowRun?.logs ?? null}
                            toolResults={workflowRun?.gathered_context?.tool_results}
                        />
                    </ConversationRailFrame>
                </div>

                {/* For whoever builds the agent: open by default when the call
                    was opened from the agent, folded away from the Calls list. */}
                <details
                    className="group min-w-0 self-start rounded-xl border border-line bg-panel xl:col-start-1 xl:row-start-2 xl:max-h-full xl:min-h-0 xl:overflow-y-auto"
                    open={!cameFromWorkspace}
                >
                    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-5 py-3 text-[14.5px] font-semibold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 [&::-webkit-details-marker]:hidden">
                        <span>
                            Technical details
                            <span className="ml-2 font-normal text-ink-3">for whoever set up your agent</span>
                        </span>
                        <ChevronDown className="size-4 text-ink-3 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden />
                    </summary>
                    <div className="space-y-6 border-t border-line-soft p-4 sm:p-5">
                        <div className="flex flex-wrap items-center gap-2">
                            <CopyDebugIdButton label="Agent ID" value={workflowId} />
                            <CopyDebugIdButton label="Run ID" value={runId} />
                            {workflowRun?.gathered_context?.trace_url && (
                                <Button asChild size="sm" variant="outline" className="gap-2">
                                    <a
                                        href={String(workflowRun.gathered_context.trace_url)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    >
                                        <ExternalLink className="h-4 w-4" aria-hidden />
                                        Trace
                                    </a>
                                </Button>
                            )}
                        </div>

                        <RunMetricsSection
                            costInfo={workflowRun?.cost_info ?? null}
                            logs={workflowRun?.logs ?? null}
                            gatheredContext={workflowRun?.gathered_context ?? null}
                        />

                        <SkillsLoadedSection gatheredContext={workflowRun?.gathered_context ?? null} />

                        {!isTextChatRun && hasSplitTracks && (
                            <SplitTracksSection
                                userRecordingUrl={userSplitRecordingUrl as string}
                                botRecordingUrl={botSplitRecordingUrl as string}
                            />
                        )}

                        <div className="grid gap-6 md:grid-cols-2">
                            <ContextDisplay
                                title="Initial Context"
                                context={workflowRun?.initial_context ?? null}
                            />
                            <ContextDisplay
                                title="Gathered Context"
                                context={workflowRun?.gathered_context ?? null}
                            />
                        </div>

                        {workflowRun?.annotations && Object.keys(workflowRun.annotations).length > 0 && (
                            <ContextDisplay
                                title="QA Results"
                                context={workflowRun.annotations as Record<string, string | number | boolean | object>}
                            />
                        )}
                    </div>
                </details>
            </div>
        );
    }
    else {
        returnValue = (
            <div className="flex h-full items-center justify-center p-6">
                <Card className="w-full max-w-xl border-border">
                    <CardHeader className="space-y-2">
                        <CardTitle className="text-2xl">Call details unavailable</CardTitle>
                        <p className="text-sm text-muted-foreground">
                            This call does not have a details view yet. Go back to the agent to continue testing or make changes.
                        </p>
                    </CardHeader>
                    <CardFooter className="gap-2">
                        <Button asChild variant="outline" className="gap-2">
                            <Link href={backHref}>
                                <ArrowLeft className="h-4 w-4" />
                                {backLabel}
                            </Link>
                        </Button>
                        <Button asChild className="gap-2">
                            <Link href={`/workflow/${workflowId}`}>
                                Customize Agent
                            </Link>
                        </Button>
                    </CardFooter>
                </Card>
            </div>
        );
    }

    return (
        <>
            {returnValue}
            {dialog}

            {/* Only points at something when the agent link is on screen — in
                agent context the shell already offers the editor. */}
            {showRunDetailsView && cameFromWorkspace && workflowName && !isMobile && (
                <OnboardingTooltip
                    tooltipKey="customize_workflow"
                    title='Customize your agent'
                    targetRef={agentLinkRef}
                    message="Edit your agent to adjust the voice agent's behavior, add new steps, or modify the conversation flow."
                    showNext={false}
                />
            )}
        </>
    );
}
