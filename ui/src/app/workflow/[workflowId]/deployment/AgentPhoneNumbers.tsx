"use client";

import { ArrowRight, Loader2, Phone, PhoneOff, Plus } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet,
    listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet,
    updatePhoneNumberApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersPhoneNumberIdPut,
} from "@/client/sdk.gen";
import type { PhoneNumberResponse, TelephonyConfigurationListItem } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/** A workspace number with the provider it comes from. */
export interface WorkspaceNumber {
    number: PhoneNumberResponse;
    provider: TelephonyConfigurationListItem;
}

/**
 * Whether a number can be pointed at an agent, and what happens if it is.
 * Inactive numbers and numbers on a provider that's turned off can't take
 * calls, so connecting them would look done without working.
 */
export function numberAvailability(
    { number, provider }: WorkspaceNumber,
    agentId: number,
): { selectable: boolean; note: string } {
    if (provider.inactive) return { selectable: false, note: `${provider.name} is turned off` };
    if (!number.is_active) return { selectable: false, note: "Number is turned off" };
    if (number.inbound_workflow_id === agentId) return { selectable: false, note: "Already answered by this agent" };
    if (number.inbound_workflow_id) {
        return { selectable: true, note: `Now answered by ${number.inbound_workflow_name ?? `agent #${number.inbound_workflow_id}`}` };
    }
    return { selectable: true, note: "Not answered by any agent" };
}

function NumberLine({ item, note }: { item: WorkspaceNumber; note?: string }) {
    return (
        <span className="min-w-0">
            <span className="block truncate font-mono text-[14px] text-ink">{item.number.address}</span>
            <span className="block truncate text-[12.5px] text-ink-3">
                {[item.number.label, item.provider.name, note].filter(Boolean).join(" · ")}
            </span>
        </span>
    );
}

interface AgentPhoneNumbersProps {
    agentId: number;
    agentName: string;
    /** Called once the section has finished loading (or can't load). */
    onSettled?: () => void;
}

/**
 * Deployment → Phone: the numbers that ring this agent, and a one-step way to
 * point another workspace number at it. Numbers themselves are added under
 * Telephony, where the provider account lives.
 */
export function AgentPhoneNumbers({ agentId, agentName, onSettled }: AgentPhoneNumbersProps) {
    const { user, loading: authLoading, getAccessToken } = useAuth();
    const { can, orgContext, loading: orgLoading } = useOrgConfig();
    // `can` is false for everything until the organization has loaded. If
    // that load fails, try anyway: the API still enforces the permissions
    // and a refusal shows as an error with "Try again".
    const permissionsLoaded = orgContext !== null || !orgLoading;
    const permissionsKnown = orgContext !== null;
    const canRead = !permissionsKnown || can("telephony:read");
    const canWrite = !permissionsKnown || can("telephony:write");

    const [providers, setProviders] = useState<TelephonyConfigurationListItem[] | null>(null);
    const [numbers, setNumbers] = useState<WorkspaceNumber[]>([]);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [pickerOpen, setPickerOpen] = useState(false);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [savingId, setSavingId] = useState<number | null>(null);

    const load = useCallback(async () => {
        setLoadError(null);
        try {
            const headers = { Authorization: `Bearer ${await getAccessToken()}` };
            const list = await listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet({ headers });
            if (list.error) {
                setLoadError(detailFromError(list.error, "Couldn’t load your phone numbers"));
                return;
            }
            const configs = list.data?.configurations ?? [];
            // Every provider is asked: `phone_number_count` only counts active
            // numbers, and a turned-off number can still be pointed at this agent.
            const perProvider = await Promise.all(
                configs.map(async (config) => {
                    const res = await listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet({
                        headers,
                        path: { config_id: config.id },
                    });
                    if (res.error) throw new Error(detailFromError(res.error, "Couldn’t load your phone numbers"));
                    return (res.data?.phone_numbers ?? []).map((number) => ({ number, provider: config }));
                }),
            );
            setProviders(configs);
            setNumbers(perProvider.flat());
        } catch (error) {
            setLoadError(error instanceof Error ? error.message : "Couldn’t load your phone numbers");
        }
    }, [getAccessToken]);

    const hasFetched = useRef(false);
    useEffect(() => {
        if (authLoading || !user || !canRead || hasFetched.current) return;
        hasFetched.current = true;
        void load();
    }, [authLoading, user, canRead, load]);

    // Tell the page once this section has its final height, so a #website
    // link below it can be scrolled to without landing short.
    const settled = permissionsLoaded && (!canRead || loadError !== null || providers !== null);
    useEffect(() => {
        if (settled) onSettled?.();
    }, [settled, onSettled]);

    const route = async (item: WorkspaceNumber, inboundAgentId: number | null) => {
        setSavingId(item.number.id);
        try {
            const res = await updatePhoneNumberApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersPhoneNumberIdPut({
                headers: { Authorization: `Bearer ${await getAccessToken()}` },
                path: { config_id: item.provider.id, phone_number_id: item.number.id },
                body:
                    inboundAgentId === null
                        ? { clear_inbound_workflow: true }
                        : { inbound_workflow_id: inboundAgentId },
            });
            if (res.error) throw new Error(detailFromError(res.error, "Couldn’t update the number"));
            const sync = res.data?.provider_sync;
            if (sync && !sync.ok) {
                toast.warning(sync.message ?? `Saved, but ${item.provider.name} didn’t accept the change yet.`);
            } else {
                toast.success(
                    inboundAgentId === null
                        ? `${item.number.address} no longer rings ${agentName}`
                        : `Calls to ${item.number.address} now go to ${agentName}`,
                );
            }
            setPickerOpen(false);
            await load();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "Couldn’t update the number");
        } finally {
            setSavingId(null);
        }
    };

    const mine = numbers.filter(({ number }) => number.inbound_workflow_id === agentId);
    const others = numbers.filter(({ number }) => number.inbound_workflow_id !== agentId);
    const selected = others.find(({ number }) => number.id === selectedId) ?? null;
    const singleProvider = providers?.length === 1 ? providers[0] : null;
    const addNumberHref = singleProvider ? `/telephony-configurations/${singleProvider.id}` : "/telephony-configurations";

    let body: ReactNode;
    if (!permissionsLoaded) {
        body = <Skeleton className="h-14 rounded-lg" />;
    } else if (!canRead) {
        body = (
            <p className="text-[13.5px] text-ink-2">
                Ask a workspace admin to connect a phone number to this agent.
            </p>
        );
    } else if (loadError) {
        body = (
            <div className="flex flex-wrap items-center gap-3">
                <p className="text-[13.5px] text-danger">{loadError}</p>
                <Button variant="outline" size="sm" onClick={() => void load()}>
                    Try again
                </Button>
            </div>
        );
    } else if (providers === null) {
        body = <Skeleton className="h-14 rounded-lg" />;
    } else if (numbers.length === 0) {
        body = (
            <div className="rounded-lg border border-dashed border-line bg-panel-2 px-4 py-5">
                <p className="text-[14px] font-medium text-ink">
                    {providers.length === 0 ? "Your workspace has no phone numbers yet" : "No numbers added yet"}
                </p>
                <p className="mt-1 text-[13px] text-ink-2">
                    {providers.length === 0
                        ? "Connect the phone provider you buy numbers from, like Twilio, once. Then come back here and pick a number for this agent."
                        : `Add a number from ${singleProvider?.name ?? "your phone provider"}, then pick it here.`}
                </p>
                {canWrite && (
                    <Button asChild size="sm" className="mt-3.5">
                        <Link href={providers.length === 0 ? "/telephony-configurations" : addNumberHref}>
                            {providers.length === 0 ? "Set up phone numbers" : "Add a number"}
                            <ArrowRight />
                        </Link>
                    </Button>
                )}
            </div>
        );
    } else {
        body = (
            <div className="space-y-3">
                {mine.length > 0 ? (
                    <ul className="divide-y divide-line-soft rounded-lg border border-line">
                        {mine.map((item) => (
                            <li key={item.number.id} className="flex items-center gap-3 px-4 py-3">
                                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ok-dim text-ok">
                                    <Phone className="size-4" aria-hidden />
                                </span>
                                <NumberLine item={item} note={item.number.is_active ? undefined : "turned off"} />
                                {canWrite && (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="ml-auto text-ink-3 hover:text-danger"
                                        disabled={savingId !== null}
                                        onClick={() => void route(item, null)}
                                    >
                                        {savingId === item.number.id ? <Loader2 className="animate-spin" /> : <PhoneOff />}
                                        Disconnect
                                    </Button>
                                )}
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-[13.5px] text-ink-2">This agent doesn’t answer a phone number yet.</p>
                )}
                {canWrite && (
                    <div className="flex flex-wrap items-center gap-2">
                        {others.length > 0 && (
                            <Button
                                size="sm"
                                variant={mine.length > 0 ? "outline" : "default"}
                                onClick={() => {
                                    setSelectedId(null);
                                    setPickerOpen(true);
                                }}
                            >
                                <Phone />
                                Connect a phone number
                            </Button>
                        )}
                        <Button asChild size="sm" variant="ghost" className="text-ink-2">
                            <Link href={addNumberHref}>
                                <Plus />
                                Add a new number
                            </Link>
                        </Button>
                    </div>
                )}
            </div>
        );
    }

    return (
        <section id="phone" aria-labelledby="phone-title" className="scroll-mt-6 rounded-lg border border-line bg-card">
            <header className="border-b border-line-soft px-5 py-4">
                <h2 id="phone-title" className="flex items-center gap-2 text-[15px] font-semibold text-ink">
                    <Phone className="size-4 text-ink-3" aria-hidden />
                    Phone
                </h2>
                <p className="mt-1 text-[13px] text-ink-2">
                    Callers ring a number and {agentName} answers.
                </p>
            </header>
            <div className="px-5 py-4">{body}</div>

            <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>Connect a phone number</DialogTitle>
                        <DialogDescription>Pick the number callers will ring to reach {agentName}.</DialogDescription>
                    </DialogHeader>
                    <div role="radiogroup" aria-label="Phone numbers" className="max-h-80 space-y-2 overflow-y-auto">
                        {others.map((item) => {
                            const { selectable, note } = numberAvailability(item, agentId);
                            const checked = selectedId === item.number.id;
                            return (
                                <button
                                    key={item.number.id}
                                    type="button"
                                    role="radio"
                                    aria-checked={checked}
                                    disabled={!selectable}
                                    onClick={() => setSelectedId(item.number.id)}
                                    className={cn(
                                        "flex w-full items-center gap-3 rounded-lg border px-3.5 py-3 text-left transition-colors",
                                        checked ? "border-brand bg-brand-dim" : "border-line hover:border-ink-3",
                                        !selectable && "cursor-not-allowed opacity-55 hover:border-line",
                                    )}
                                >
                                    <span
                                        aria-hidden
                                        className={cn(
                                            "flex size-4 shrink-0 items-center justify-center rounded-full border",
                                            checked ? "border-brand" : "border-ink-3",
                                        )}
                                    >
                                        {checked && <span className="size-2 rounded-full bg-brand" />}
                                    </span>
                                    <NumberLine item={item} note={note} />
                                </button>
                            );
                        })}
                    </div>
                    {selected?.number.inbound_workflow_id && (
                        <p className="rounded-md bg-amber-dim px-3 py-2 text-[12.5px] text-amber">
                            {selected.number.inbound_workflow_name ?? "Another agent"} will stop answering{" "}
                            {selected.number.address}.
                        </p>
                    )}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setPickerOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            disabled={!selected || savingId !== null}
                            onClick={() => selected && void route(selected, agentId)}
                        >
                            {savingId !== null && <Loader2 className="animate-spin" />}
                            Connect
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </section>
    );
}
