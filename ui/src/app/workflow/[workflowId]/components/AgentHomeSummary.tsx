"use client";

import { ArrowRight, Globe2, Mic, Phone, PhoneCall, PhoneIncoming, PhoneOutgoing } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";

import {
    getWorkflowRunsApiV1WorkflowWorkflowIdRunsGet,
    listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet,
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet,
} from "@/client/sdk.gen";
import type { WorkflowRunResponseSchema } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { WORKFLOW_RUN_MODES } from "@/constants/workflowRunModes";
import { useAgentShell } from "@/context/AgentShellContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { formatLastCall } from "@/lib/agentList";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/**
 * The top of an agent: what state it is in, how callers reach it, and the
 * one thing an owner most wants to do — hear it. Only real data: a number is
 * shown only when one rings this agent, calls only when there have been some.
 *
 * Sits above Business facts, which is where opening an agent lands.
 */

type Numbers = { state: "loading" } | { state: "hidden" } | { state: "ready"; numbers: string[] };
type RecentCalls = { state: "loading" } | { state: "hidden" } | { state: "ready"; runs: WorkflowRunResponseSchema[] };

const RECENT_LIMIT = 3;

/** The agent's status in plain words, from the API's version status. */
export function agentStatusWords(versionStatus: string | null | undefined): {
    label: string;
    hint: string;
    tone: "ok" | "warn" | "mute";
} {
    if (versionStatus === "published") {
        return { label: "Live", hint: "", tone: "ok" };
    }
    if (versionStatus === "draft") {
        return {
            label: "Changes not live yet",
            hint: "Publish them from Conversation when you're happy.",
            tone: "warn",
        };
    }
    return { label: "Not live yet", hint: "Publish it from Conversation when you're happy.", tone: "mute" };
}

function callKind(run: WorkflowRunResponseSchema): { label: string; Icon: typeof Phone } {
    if (run.mode === WORKFLOW_RUN_MODES.SMALL_WEBRTC || run.mode === WORKFLOW_RUN_MODES.WEBRTC) {
        return { label: "Test call in the browser", Icon: Mic };
    }
    if (run.mode === WORKFLOW_RUN_MODES.TEXTCHAT) return { label: "Test chat", Icon: Globe2 };
    if (run.call_type === "outbound") return { label: "Outgoing call", Icon: PhoneOutgoing };
    return { label: "Incoming call", Icon: PhoneIncoming };
}

function formatDuration(seconds: unknown): string | null {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
    const whole = Math.round(seconds);
    if (whole < 60) return `${whole} sec`;
    const minutes = Math.floor(whole / 60);
    const rest = whole % 60;
    return rest ? `${minutes} min ${rest} sec` : `${minutes} min`;
}

/** A whole-card link in the Overview's style: icon tile, title, one line, arrow. */
function SummaryCard({
    href,
    icon,
    title,
    children,
    cta,
}: {
    href: string;
    icon: ReactNode;
    title: string;
    children: ReactNode;
    cta: string;
}) {
    return (
        <Link
            href={href}
            className="group block h-full rounded-lg outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
        >
            <div className="flex h-full items-start gap-3.5 rounded-lg border border-line bg-panel px-4 py-3.5 transition-all duration-150 group-hover:-translate-y-0.5 group-hover:border-brand/50 group-hover:shadow-md motion-reduce:transition-none motion-reduce:group-hover:translate-y-0">
                <span className="grid size-10 flex-none place-items-center rounded-lg bg-brand-dim text-brand [&_svg]:size-5" aria-hidden>
                    {icon}
                </span>
                <div className="min-w-0 flex-1">
                    <h3 className="text-[14.5px] font-semibold text-foreground">{title}</h3>
                    <div className="mt-0.5 text-[13px] leading-snug text-ink-2">{children}</div>
                    <span className="mt-1.5 inline-flex items-center gap-1 text-[13px] font-medium text-brand">
                        {cta}
                        <ArrowRight
                            className="size-3.5 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none"
                            aria-hidden
                        />
                    </span>
                </div>
            </div>
        </Link>
    );
}

/**
 * Open the test panel and move focus to its start button, so the click does
 * something visible even when the panel is already open beside the page.
 */
export function talkToAgent(openTester: () => void) {
    openTester();
    // The sheet mounts on the next frames; the desktop rail is already there.
    window.setTimeout(() => {
        const buttons = document.querySelectorAll<HTMLButtonElement>("[data-test-call-start]");
        const visible = Array.from(buttons).find((b) => b.offsetParent !== null && !b.disabled);
        visible?.focus();
    }, 350);
}

export function AgentHomeSummary({ workflowId }: { workflowId: number }) {
    const { agent, loading: agentLoading, openTester } = useAgentShell();
    const { user, loading: authLoading, getAccessToken } = useAuth();
    const { can, orgContext } = useOrgConfig();
    const timezone = useOrganizationTimezone();
    // Until the organisation has loaded, `can` says no to everything; asking
    // anyway is safe — the API still decides — and avoids a blank card.
    const canReadPhones = orgContext === null || can("telephony:read");

    const [numbers, setNumbers] = useState<Numbers>({ state: "loading" });
    const [recent, setRecent] = useState<RecentCalls>({ state: "loading" });

    useEffect(() => {
        if (authLoading || !user) return;
        if (!canReadPhones) {
            setNumbers({ state: "hidden" });
            return;
        }
        let ignore = false;
        const load = async () => {
            try {
                const headers = { Authorization: `Bearer ${await getAccessToken()}` };
                const list = await listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet({ headers });
                if (list.error) throw new Error("phones");
                const perProvider = await Promise.all(
                    (list.data?.configurations ?? []).map(async (config) => {
                        const res = await listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet({
                            headers,
                            path: { config_id: config.id },
                        });
                        if (res.error) throw new Error("phones");
                        return res.data?.phone_numbers ?? [];
                    }),
                );
                const mine = perProvider
                    .flat()
                    .filter((n) => n.inbound_workflow_id === workflowId && n.is_active)
                    .map((n) => n.address);
                if (!ignore) setNumbers({ state: "ready", numbers: mine });
            } catch {
                // The card still links to Deployment, which has its own retry.
                if (!ignore) setNumbers({ state: "hidden" });
            }
        };
        void load();
        return () => {
            ignore = true;
        };
    // Not keyed on getAccessToken: a new function each render must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [authLoading, user?.id, canReadPhones, workflowId]);

    const totalRuns = agent?.totalRuns ?? 0;
    useEffect(() => {
        if (authLoading || !user || agentLoading) return;
        if (totalRuns === 0) {
            setRecent({ state: "ready", runs: [] });
            return;
        }
        let ignore = false;
        const load = async () => {
            try {
                const res = await getWorkflowRunsApiV1WorkflowWorkflowIdRunsGet({
                    path: { workflow_id: workflowId },
                    query: { page: 1, limit: RECENT_LIMIT, sort_by: "created_at", sort_order: "desc" },
                });
                if (res.error) throw new Error("runs");
                if (!ignore) setRecent({ state: "ready", runs: res.data?.runs ?? [] });
            } catch {
                if (!ignore) setRecent({ state: "hidden" });
            }
        };
        void load();
        return () => {
            ignore = true;
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [authLoading, user?.id, agentLoading, totalRuns, workflowId]);

    if (!agent) {
        return (
            <div
                className="rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-5 py-5 sm:px-6"
                aria-busy="true"
                aria-label="Loading your agent"
            >
                <Skeleton className="h-5 w-20 rounded-full" />
                <Skeleton className="mt-3 h-7 w-64 max-w-full" />
                <Skeleton className="mt-2 h-4 w-80 max-w-full" />
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                    <Skeleton className="h-[92px] rounded-lg" />
                    <Skeleton className="h-[92px] rounded-lg" />
                </div>
            </div>
        );
    }

    const status = agentStatusWords(agent.versionStatus);
    const base = `/workflow/${workflowId}`;

    return (
        <section
            aria-labelledby="agent-home-title"
            className="rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-5 py-5 sm:px-6"
        >
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                    <span
                        className={cn(
                            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12.5px] font-medium",
                            status.tone === "ok" && "bg-ok-dim text-ok",
                            status.tone === "warn" && "bg-amber-dim text-amber",
                            status.tone === "mute" && "bg-panel-2 text-ink-2",
                        )}
                    >
                        <span className="size-1.5 rounded-full bg-current" aria-hidden />
                        {status.label}
                    </span>
                    <h2
                        id="agent-home-title"
                        className="mt-2 break-words text-[22px] font-bold leading-tight tracking-tight text-foreground"
                    >
                        {agent.name}
                    </h2>
                    <p className="mt-1 max-w-xl text-[14.5px] text-ink-2">
                        {status.hint ? `${status.hint} ` : ""}Check what it tells callers below, then talk to it to hear how
                        it sounds.
                    </p>
                </div>
                <Button size="lg" onClick={() => talkToAgent(openTester)} className="h-11 w-full shrink-0 text-[15px] sm:w-auto">
                    <Mic className="size-4" aria-hidden />
                    Talk to your agent
                </Button>
            </div>

            <ul className="mt-5 grid gap-3 sm:grid-cols-2">
                <li>
                    {numbers.state === "loading" ? (
                        <Skeleton className="h-[92px] rounded-lg" />
                    ) : numbers.state === "ready" && numbers.numbers.length > 0 ? (
                        <SummaryCard href={`${base}/deployment#phone`} icon={<Phone />} title="Phone number" cta="Manage">
                            <span className="font-mono text-[13.5px] text-foreground">{numbers.numbers[0]}</span>
                            {numbers.numbers.length > 1 && (
                                <span className="text-ink-3"> and {numbers.numbers.length - 1} more</span>
                            )}
                        </SummaryCard>
                    ) : numbers.state === "ready" ? (
                        <SummaryCard
                            href={`${base}/deployment#phone`}
                            icon={<Phone />}
                            title="Phone number"
                            cta="Connect a phone number"
                        >
                            Not connected yet, so callers can&apos;t reach it.
                        </SummaryCard>
                    ) : (
                        <SummaryCard href={`${base}/deployment`} icon={<Phone />} title="How callers reach it" cta="See phone and website">
                            Put it on a phone number or your website.
                        </SummaryCard>
                    )}
                </li>
                <li>
                    <SummaryCard
                        href={`${base}/runs`}
                        icon={<PhoneCall />}
                        title="Calls"
                        cta={totalRuns > 0 ? "See all calls" : "Open calls"}
                    >
                        {totalRuns === 0
                            ? "No calls yet. Test calls show up here too."
                            : `${totalRuns.toLocaleString("en-IE")} ${totalRuns === 1 ? "call" : "calls"} so far.`}
                    </SummaryCard>
                </li>
            </ul>

            {recent.state === "ready" && recent.runs.length > 0 && (
                <div className="mt-5">
                    <h3 className="text-[13px] font-semibold text-ink-2">Recent calls</h3>
                    <ul className="mt-2 divide-y divide-line-soft overflow-hidden rounded-lg border border-line bg-panel">
                        {recent.runs.map((run) => {
                            const kind = callKind(run);
                            const duration = formatDuration(
                                (run.cost_info as { call_duration_seconds?: unknown } | null)?.call_duration_seconds,
                            );
                            return (
                                <li key={run.id}>
                                    <Link
                                        href={`${base}/run/${run.id}`}
                                        className="flex min-h-12 items-center gap-3 px-4 py-2.5 outline-none transition-colors hover:bg-panel-2 focus-visible:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/40 motion-reduce:transition-none"
                                    >
                                        <kind.Icon className="size-4 shrink-0 text-ink-3" aria-hidden />
                                        <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground">
                                            {kind.label}
                                        </span>
                                        <span className="shrink-0 text-[12.5px] text-ink-3" suppressHydrationWarning>
                                            {[duration, formatLastCall(run.created_at, timezone)].filter(Boolean).join(" · ")}
                                        </span>
                                        <ArrowRight className="size-3.5 shrink-0 text-ink-3" aria-hidden />
                                    </Link>
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}
        </section>
    );
}
