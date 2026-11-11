"use client";

import { Check, ChevronDown, Copy, Loader2, Phone } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getPhoneSetupApiV1WorkflowWorkflowIdPhoneSetupGet,
    getPlatformNumberApiV1WorkflowWorkflowIdPlatformNumberPost,
    listAvailablePlatformNumbersApiV1PlatformNumbersAvailableGet,
    updatePhoneSetupApiV1WorkflowWorkflowIdPhoneSetupPut,
} from "@/client/sdk.gen";
import type { AgentPhoneNumber, AvailablePlatformNumber, PhoneSetupResponse } from "@/client/types.gen";
import { SUPPORT_MAILTO } from "@/components/SupportLink";
import { Button } from "@/components/ui/button";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

import { AgentPhoneNumbers } from "./AgentPhoneNumbers";
import {
    displayNumber,
    FORWARD_OPTIONS,
    forwardingCode,
    type ForwardWhen,
    isPublicNumber,
    SETUP_METHODS,
    type SetupMethod,
    UNDO_CODE,
} from "./phoneForwarding";

const LOAD_FAILED = "Couldn’t load how callers reach your agent";

/** The number the setup is about: the first one that can take calls. */
export function primaryNumber(numbers: AgentPhoneNumber[]): AgentPhoneNumber | null {
    return numbers.find((n) => n.is_active && !n.provider_inactive) ?? numbers[0] ?? null;
}

/** A value with a Copy button; `display` is what's shown when it differs from what's copied. */
function CopyValue({
    value,
    display,
    label,
    mono = false,
}: {
    value: string;
    display?: string;
    label: string;
    mono?: boolean;
}) {
    const copy = async () => {
        try {
            await copyTextToClipboard(value);
            toast.success(`${label} copied`);
        } catch {
            toast.error("Couldn’t copy. Select it and copy it by hand.");
        }
    };
    return (
        <div className="inline-flex max-w-full items-center gap-3 rounded-lg border border-line bg-card py-2 pl-3.5 pr-2">
            <span className={cn("min-w-0 break-all text-[15px] text-ink", mono && "font-mono text-[14px] font-semibold")}>
                {display ?? value}
            </span>
            <Button type="button" variant="outline" size="sm" onClick={() => void copy()} aria-label={`Copy ${label.toLowerCase()}`}>
                <Copy aria-hidden />
                Copy
            </Button>
        </div>
    );
}

function Step({ n, title, done = false, children }: { n: number; title: string; done?: boolean; children: ReactNode }) {
    return (
        <li className="grid grid-cols-[28px_minmax(0,1fr)] gap-3">
            <span
                aria-hidden
                className={cn(
                    "flex size-7 items-center justify-center rounded-full text-caption font-semibold",
                    done ? "bg-ok text-white" : "bg-brand text-white",
                )}
            >
                {done ? <Check className="size-4" /> : n}
            </span>
            <div className="min-w-0 pt-0.5">
                <h3 className="text-[14.5px] font-semibold text-ink">
                    {title}
                    {done && <span className="sr-only"> (done)</span>}
                </h3>
                <div className="mt-1 space-y-2.5 text-sm text-ink-2">{children}</div>
            </div>
        </li>
    );
}

function Code({ children }: { children: ReactNode }) {
    return <code className="rounded bg-panel px-1.5 py-px font-mono text-[12px] text-ink">{children}</code>;
}

interface PhoneSetupProps {
    agentId: number;
    agentName: string;
    /** Called once the section has finished loading (or can't load). */
    onSettled?: () => void;
}

/**
 * Deployment → Phone (mocks/transfer.png, part 1): how callers reach this
 * agent. Three ways in: forward the business's existing number, get a new one,
 * or forward the owner's mobile. "Check it works" turns green once the
 * agent's number has had a real inbound call since the setup was chosen; the
 * screen never places a call itself.
 */
export function PhoneSetup({ agentId, agentName, onSettled }: PhoneSetupProps) {
    const { user, loading: authLoading, getAccessToken } = useAuth();
    const { can, orgContext, loading: orgLoading } = useOrgConfig();
    const permissionsLoaded = orgContext !== null || !orgLoading;
    const permissionsKnown = orgContext !== null;
    const canRead = !permissionsKnown || can("telephony:read");
    const canWrite = !permissionsKnown || can("telephony:write");

    const [data, setData] = useState<PhoneSetupResponse | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [method, setMethod] = useState<SetupMethod>("keep_existing");
    const [forwardWhen, setForwardWhen] = useState<ForwardWhen>("no_answer");
    const [checking, setChecking] = useState(false);
    const [checkedOnce, setCheckedOnce] = useState(false);
    // The owner's own picks win over what loads later.
    const touched = useRef(false);

    const apply = useCallback((next: PhoneSetupResponse) => {
        setData(next);
        const saved = primaryNumber(next.numbers)?.setup;
        if (saved && !touched.current) {
            setMethod(saved.method);
            if (saved.forward_when) setForwardWhen(saved.forward_when);
        }
    }, []);

    const load = useCallback(async () => {
        setLoadError(null);
        try {
            const res = await getPhoneSetupApiV1WorkflowWorkflowIdPhoneSetupGet({
                headers: { Authorization: `Bearer ${await getAccessToken()}` },
                path: { workflow_id: agentId },
            });
            if (res.error || !res.data) {
                setLoadError(detailFromError(res.error, LOAD_FAILED));
                return;
            }
            apply(res.data);
        } catch {
            setLoadError(LOAD_FAILED);
        }
    }, [agentId, apply, getAccessToken]);

    const hasFetched = useRef(false);
    useEffect(() => {
        if (authLoading || !user || !canRead || hasFetched.current) return;
        hasFetched.current = true;
        void load();
    }, [authLoading, user, canRead, load]);

    const settled = permissionsLoaded && (!canRead || loadError !== null || data !== null);
    useEffect(() => {
        if (settled) onSettled?.();
    }, [settled, onSettled]);

    const primary = data ? primaryNumber(data.numbers) : null;
    const saved = primary?.setup ?? null;
    const wantedWhen = method === "new_number" ? null : forwardWhen;
    const savedMatches = !!saved && saved.method === method && (saved.forward_when ?? null) === wantedWhen;
    const received = savedMatches && primary?.check.status === "received";

    // While the owner is waiting on a test call, look again now and then.
    const waiting = savedMatches && primary?.check.status === "waiting";
    useEffect(() => {
        if (!waiting) return;
        const timer = window.setInterval(() => void load(), 15000);
        return () => window.clearInterval(timer);
    }, [waiting, load]);

    /** Save the choice if it changed, then read the latest status. */
    const check = async () => {
        if (!primary) return;
        setChecking(true);
        try {
            const headers = { Authorization: `Bearer ${await getAccessToken()}` };
            const res = savedMatches
                ? await getPhoneSetupApiV1WorkflowWorkflowIdPhoneSetupGet({ headers, path: { workflow_id: agentId } })
                : await updatePhoneSetupApiV1WorkflowWorkflowIdPhoneSetupPut({
                      headers,
                      path: { workflow_id: agentId },
                      body: { phone_number_id: primary.id, method, forward_when: wantedWhen },
                  });
            if (res.error || !res.data) throw new Error(detailFromError(res.error, "Couldn’t check just now"));
            apply(res.data);
            setCheckedOnce(true);
            const first = primaryNumber(res.data.numbers);
            if (first?.check.status !== "received") {
                toast.info("No call has reached your agent yet. We’ll keep checking while this page is open.");
            }
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "Couldn’t check just now");
        } finally {
            setChecking(false);
        }
    };

    let body: ReactNode;
    if (!permissionsLoaded || (canRead && data === null && loadError === null)) {
        body = <Skeleton className="h-40 rounded-lg" />;
    } else if (!canRead) {
        body = <p className="text-sm text-ink-2">Ask a workspace admin to set up a phone number for this agent.</p>;
    } else if (loadError || !data) {
        body = (
            <div className="flex flex-wrap items-center gap-3">
                <p className="text-sm text-danger">{loadError ?? LOAD_FAILED}</p>
                <Button variant="outline" size="sm" onClick={() => void load()}>
                    Try again
                </Button>
            </div>
        );
    } else {
        const checkStep = (n: number) => (
            <Step n={n} title="Check it works" done={received}>
                {received && primary ? (
                    <>
                        <p className="text-ok">
                            It works. Your agent answered its first call
                            {primary.check.first_call_at ? ` on ${new Date(primary.check.first_call_at).toLocaleString()}` : ""}.
                        </p>
                        {primary.check.forwarded_from && (
                            <p>Forwarded from your number {displayNumber(primary.check.forwarded_from)}.</p>
                        )}
                    </>
                ) : (
                    <>
                        <p>
                            {method === "new_number"
                                ? "Ring your agent’s number from your own phone. When your agent answers, this step turns green."
                                : "Ring your own number from another phone. When your agent answers, this step turns green."}
                        </p>
                        {checkedOnce && savedMatches && (
                            <p role="status" className="flex items-center gap-2 text-ink-2">
                                <Loader2 className="size-3.5 animate-spin text-ink-3" />
                                No call yet. We’ll keep looking while this page is open.
                            </p>
                        )}
                        {canWrite && (
                            <Button size="sm" onClick={() => void check()} disabled={checking}>
                                {checking && <Loader2 className="animate-spin" />}
                                I’ve set it up – check now
                            </Button>
                        )}
                    </>
                )}
            </Step>
        );

        const numberStep = primary ? (
            <Step n={1} title="Your agent’s number">
                <p>
                    {method === "new_number"
                        ? "Give this number to your callers: on your website, your Google listing and your cards."
                        : "Calls you forward go here. You don’t share this number with anyone."}
                </p>
                <CopyValue
                    value={primary.address_normalized}
                    display={displayNumber(primary.address_normalized)}
                    label="Number"
                />
                {primary.lightmove_number && <p className="text-caption text-ink-3">Provided by LightMove.</p>}
            </Step>
        ) : null;

        let steps: ReactNode;
        if (!primary) {
            steps = (
                <ol className="space-y-5">
                    <Step n={1} title="Your agent’s number">
                        <p>
                            {method === "new_number"
                                ? "Pick a number for your agent. Callers ring it and your agent answers."
                                : "Your agent needs its own number first. Calls you forward go there; you don’t share it with anyone."}
                        </p>
                        {canWrite ? (
                            <GetNumber
                                agentId={agentId}
                                available={data.platform_numbers_available}
                                onGot={(next) => {
                                    apply(next);
                                    toast.success(`${agentName} has a phone number`);
                                }}
                            />
                        ) : (
                            <p className="text-ink-3">Ask a workspace admin to get a number for this agent.</p>
                        )}
                    </Step>
                </ol>
            );
        } else if (!isPublicNumber(primary.address_normalized)) {
            // An extension on the customer's own phone system (e.g. Asterisk
            // "7000"): calls reach it inside that system, but no mobile or
            // landline can forward to it, so don't offer forwarding codes.
            steps = (
                <ol className="space-y-5">
                    <Step n={1} title="Your agent’s number">
                        <p>
                            <strong>{primary.address_normalized}</strong> is an extension on your own phone system, not a
                            phone number. Calls made inside that system to {primary.address_normalized} reach your agent.
                        </p>
                        {method !== "new_number" && (
                            <div role="alert" className="rounded-lg border border-amber/40 bg-amber-dim px-3.5 py-3 text-sm">
                                <p className="font-semibold text-ink">Phones can’t forward to an extension</p>
                                <p className="mt-1 text-ink-2">
                                    A mobile or landline can only forward to a full phone number. To forward your
                                    number, your agent needs one: choose <strong>Get a new number</strong> above, or add
                                    a number from your phone provider below. If you already dialled a forwarding code
                                    for {primary.address_normalized}, cancel it with <Code>{UNDO_CODE}</Code>.
                                </p>
                            </div>
                        )}
                    </Step>
                    {method === "new_number" && checkStep(2)}
                </ol>
            );
        } else if (method === "new_number") {
            steps = (
                <ol className="space-y-5">
                    {numberStep}
                    {checkStep(2)}
                </ol>
            );
        } else {
            const code = forwardingCode(primary.address_normalized, forwardWhen);
            steps = (
                <ol className="space-y-5">
                    {numberStep}
                    <Step n={2} title="When should calls go to your agent?">
                        <div role="radiogroup" aria-label="When calls go to your agent" className="grid gap-2 @md/phone:grid-cols-2">
                            {FORWARD_OPTIONS.map((option) => {
                                const checked = forwardWhen === option.value;
                                return (
                                    <button
                                        key={option.value}
                                        type="button"
                                        role="radio"
                                        aria-checked={checked}
                                        onClick={() => {
                                            touched.current = true;
                                            setForwardWhen(option.value);
                                        }}
                                        className={cn(
                                            "rounded-lg border px-3.5 py-2.5 text-left transition-colors",
                                            checked ? "border-brand bg-brand-dim" : "border-line bg-card hover:border-ink-3",
                                        )}
                                    >
                                        <span className="block text-sm font-semibold text-ink">{option.title}</span>
                                        <span className="mt-0.5 block text-caption text-ink-2">
                                            {option.body} {option.code && <Code>{option.code}</Code>}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    </Step>
                    <Step n={3} title="Turn on forwarding">
                        {code ? (
                            <>
                                <p>On most mobiles, dial this and press call:</p>
                                <CopyValue value={code} label="Code" mono />
                            </>
                        ) : (
                            <p>
                                Ask your phone company to forward calls outside your opening hours to the number
                                above. Not every phone company offers this.
                            </p>
                        )}
                        <p>
                            {method === "keep_existing"
                                ? "On a landline or office phone system, ask your phone company (eir, Vodafone, Virgin Media, BT…) to forward to the number above."
                                : "If your network doesn’t accept the code, ask your mobile network to forward to the number above."}{" "}
                            {code && (
                                <>
                                    Undo it any time with <Code>{UNDO_CODE}</Code>.
                                </>
                            )}
                        </p>
                    </Step>
                    {checkStep(4)}
                </ol>
            );
        }

        body = (
            <div className="space-y-5">
                <div role="radiogroup" aria-label="How callers reach your agent" className="grid gap-3 @2xl/phone:grid-cols-3">
                    {SETUP_METHODS.map((option) => {
                        const checked = method === option.value;
                        return (
                            <button
                                key={option.value}
                                type="button"
                                role="radio"
                                aria-checked={checked}
                                onClick={() => {
                                    touched.current = true;
                                    setMethod(option.value);
                                    setCheckedOnce(false);
                                }}
                                className={cn(
                                    "flex flex-col items-start rounded-xl border px-4 py-3.5 text-left transition-colors",
                                    checked ? "border-2 border-brand bg-brand-dim" : "border-line bg-card hover:border-ink-3",
                                )}
                            >
                                <span className="text-[14.5px] font-semibold text-ink">{option.title}</span>
                                <span className="mt-1 text-caption leading-snug text-ink-2">{option.body}</span>
                                {option.badge && (
                                    <span className="mt-2 rounded-full bg-ok-dim px-2 py-px text-[12px] font-semibold text-ok">
                                        {option.badge}
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </div>
                <div className="border-t border-line-soft pt-5">{steps}</div>
                {canWrite && <OwnProviderAccount agentId={agentId} agentName={agentName} hasNumber={!!primary} onChanged={load} />}
            </div>
        );
    }

    return (
        <section id="phone" aria-labelledby="phone-title" className="@container/phone scroll-mt-6 rounded-lg border border-line bg-card">
            <header className="border-b border-line-soft px-5 py-4">
                <h2 id="phone-title" className="flex items-center gap-2 text-[15px] font-semibold text-ink">
                    <Phone className="size-4 text-ink-3" aria-hidden />
                    How should callers reach {agentName}?
                </h2>
                <p className="mt-1 text-caption text-ink-2">You can change this later.</p>
            </header>
            <div className="px-5 py-4">{body}</div>
        </section>
    );
}

/** LightMove provides the number: pick a local or mobile number and get it. */
function GetNumber({
    agentId,
    available,
    onGot,
}: {
    agentId: number;
    available: boolean;
    onGot: (next: PhoneSetupResponse) => void;
}) {
    const { getAccessToken } = useAuth();
    const [kind, setKind] = useState<"local" | "mobile">("local");
    const [numbers, setNumbers] = useState<AvailablePlatformNumber[] | null>(null);
    const [selected, setSelected] = useState<string | null>(null);
    const [searching, setSearching] = useState(false);
    const [getting, setGetting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const search = async (nextKind: "local" | "mobile") => {
        setKind(nextKind);
        setSearching(true);
        setError(null);
        setSelected(null);
        try {
            const res = await listAvailablePlatformNumbersApiV1PlatformNumbersAvailableGet({
                headers: { Authorization: `Bearer ${await getAccessToken()}` },
                query: { kind: nextKind },
            });
            if (res.error || !res.data) throw new Error(detailFromError(res.error, "Couldn’t look up numbers"));
            setNumbers(res.data.numbers);
        } catch (e) {
            setNumbers(null);
            setError(e instanceof Error ? e.message : "Couldn’t look up numbers");
        } finally {
            setSearching(false);
        }
    };

    const get = async () => {
        if (!selected) return;
        setGetting(true);
        setError(null);
        try {
            const res = await getPlatformNumberApiV1WorkflowWorkflowIdPlatformNumberPost({
                headers: { Authorization: `Bearer ${await getAccessToken()}` },
                path: { workflow_id: agentId },
                body: { phone_number: selected },
            });
            if (res.error || !res.data) throw new Error(detailFromError(res.error, "Couldn’t get that number"));
            onGot(res.data);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Couldn’t get that number");
        } finally {
            setGetting(false);
        }
    };

    if (!available) {
        return (
            <Panel accent="sky" padding="sm">
                <div className="flex flex-wrap items-center gap-2">
                    <PanelTitle as="h4">LightMove provides the number</PanelTitle>
                    <StatusPill tone="info">Coming soon</StatusPill>
                </div>
                <PanelDescription>
                    We’re getting LightMove numbers ready.{" "}
                    <a href={SUPPORT_MAILTO} className="font-medium text-brand underline-offset-2 hover:underline">
                        Ask us
                    </a>{" "}
                    and we’ll set one up for your agent, or use your own phone provider account below.
                </PanelDescription>
            </Panel>
        );
    }

    return (
        <Panel accent="brand" padding="sm" className="space-y-3">
            <div>
                <PanelTitle as="h4">LightMove provides the number</PanelTitle>
                <PanelDescription>No phone company account needed. Pick a number and it rings your agent straight away.</PanelDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <div role="group" aria-label="Kind of number" className="inline-flex rounded-md border border-line bg-card p-0.5">
                    {(["local", "mobile"] as const).map((k) => (
                        <button
                            key={k}
                            type="button"
                            aria-pressed={numbers !== null && kind === k}
                            onClick={() => void search(k)}
                            disabled={searching}
                            className={cn(
                                "rounded px-3 py-1 text-caption font-medium",
                                numbers !== null && kind === k ? "bg-ink text-card" : "text-ink-2 hover:text-ink",
                            )}
                        >
                            {k === "local" ? "Local number" : "Mobile number"}
                        </button>
                    ))}
                </div>
                {searching && <Loader2 className="size-4 animate-spin text-ink-3" aria-label="Looking up numbers" />}
            </div>
            {numbers !== null && !searching && (
                numbers.length === 0 ? (
                    <p className="text-caption text-ink-2">No numbers of this kind right now. Try the other kind, or ask us.</p>
                ) : (
                    <div role="radiogroup" aria-label="Available numbers" className="grid gap-2 @md/phone:grid-cols-2">
                        {numbers.map((n) => {
                            const checked = selected === n.phone_number;
                            return (
                                <button
                                    key={n.phone_number}
                                    type="button"
                                    role="radio"
                                    aria-checked={checked}
                                    onClick={() => setSelected(n.phone_number)}
                                    className={cn(
                                        "rounded-lg border px-3 py-2 text-left",
                                        checked ? "border-brand bg-brand-dim" : "border-line bg-card hover:border-ink-3",
                                    )}
                                >
                                    <span className="block font-mono text-[14px] text-ink">{displayNumber(n.phone_number)}</span>
                                    {(n.locality || n.region) && (
                                        <span className="block text-[12px] text-ink-3">{n.locality ?? n.region}</span>
                                    )}
                                </button>
                            );
                        })}
                    </div>
                )
            )}
            {error && <p className="text-caption text-danger">{error}</p>}
            {numbers && numbers.length > 0 && (
                <Button size="sm" disabled={!selected || getting} onClick={() => void get()}>
                    {getting && <Loader2 className="animate-spin" />}
                    Get this number
                </Button>
            )}
        </Panel>
    );
}

/** Today's flow, kept as the advanced route: numbers from the owner's own provider account. */
function OwnProviderAccount({
    agentId,
    agentName,
    hasNumber,
    onChanged,
}: {
    agentId: number;
    agentName: string;
    hasNumber: boolean;
    onChanged: () => void;
}) {
    const [open, setOpen] = useState(false);
    return (
        <div className="border-t border-line-soft pt-3">
            <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
                className="inline-flex items-center gap-1.5 text-caption font-medium text-ink-2 hover:text-ink"
            >
                <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />
                {hasNumber ? "Manage this agent’s numbers" : "Advanced: use my own phone provider account"}
            </button>
            {open && (
                <div className="mt-3">
                    <AgentPhoneNumbers embedded agentId={agentId} agentName={agentName} onChanged={onChanged} />
                </div>
            )}
        </div>
    );
}
