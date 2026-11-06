"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AdminError, AdminLoading, StatTile } from "@/components/platform-admin/AdminStates";
import { AUDIT_ACTION_LABELS, formatEur, formatWhen, PLAN_LABELS } from "@/components/platform-admin/format";
import { OrganizationStatus } from "@/components/platform-admin/OrganizationStatus";
import { RunsTable } from "@/components/platform-admin/RunsTable";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { SectionHeading } from "@/components/ui/section-heading";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Feature,FEATURES } from "@/config/features";
import { useAppConfig } from "@/context/AppConfigContext";
import { type AdminOrganizationDetail, platformAdminApi } from "@/lib/platformAdminApi";

const FEATURE_LABELS: Record<Feature, string> = { campaigns: "Campaigns", skills: "Skills" };
const MONEY = /^\d+(\.\d{1,4})?$/;

function errorMessage(err: unknown, fallback: string): string {
    return err instanceof Error ? err.message : fallback;
}

/** Plan, per-minute rate and credit limit (Stripe billing only). */
function BillingTerms({ detail, onSaved }: { detail: AdminOrganizationDetail; onSaved: () => void }) {
    const org = detail.organization;
    const [plan, setPlan] = useState(org.plan ?? "payg");
    const [rate, setRate] = useState(org.price_per_minute_override_eur ?? "");
    const [creditLimit, setCreditLimit] = useState(org.credit_limit_eur ?? "0");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        setPlan(org.plan ?? "payg");
        setRate(org.price_per_minute_override_eur ?? "");
        setCreditLimit(org.credit_limit_eur ?? "0");
    }, [org.plan, org.price_per_minute_override_eur, org.credit_limit_eur]);

    const save = async () => {
        const changes: { plan?: string; price_per_minute_eur?: string | null; credit_limit_eur?: string } = {};
        if (plan !== (org.plan ?? "payg")) changes.plan = plan;
        const rateValue = rate.trim();
        if (rateValue !== "" && !MONEY.test(rateValue)) return toast.error("Per-minute rate: a number like 0.12");
        if (rateValue === "" ? org.price_per_minute_override_eur !== null : Number(rateValue) !== Number(org.price_per_minute_override_eur)) {
            changes.price_per_minute_eur = rateValue === "" ? null : rateValue;
        }
        const limitValue = creditLimit.trim();
        if (!/^\d+(\.\d{1,2})?$/.test(limitValue)) return toast.error("Credit limit: a number of euros, like 50");
        if (Number(limitValue) !== Number(org.credit_limit_eur ?? 0)) changes.credit_limit_eur = limitValue;
        if (Object.keys(changes).length === 0) return toast.info("Nothing changed");
        setSaving(true);
        try {
            await platformAdminApi.updateBilling(org.id, changes);
            toast.success("Billing terms saved");
            onSaved();
        } catch (err) {
            toast.error(errorMessage(err, "Could not save the billing terms"));
        } finally {
            setSaving(false);
        }
    };

    return (
        <Panel className="space-y-3">
            <PanelTitle as="h3">Plan and rates</PanelTitle>
            <div className="grid gap-3 md:grid-cols-3">
                <div className="space-y-1.5">
                    <Label htmlFor="plan">Plan</Label>
                    <Select value={plan} onValueChange={(value) => setPlan(value as typeof plan)}>
                        <SelectTrigger id="plan">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {Object.entries(PLAN_LABELS).map(([value, label]) => (
                                <SelectItem key={value} value={value}>
                                    {label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="rate">Per-minute rate, EUR</Label>
                    <Input
                        id="rate"
                        inputMode="decimal"
                        placeholder={`Plan rate (${formatEur(org.effective_price_per_minute_eur)} now)`}
                        value={rate}
                        onChange={(event) => setRate(event.target.value)}
                    />
                    <p className="text-[11px] text-ink-3">Leave empty for the plan&apos;s rate.</p>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="credit-limit">Credit limit, EUR</Label>
                    <Input
                        id="credit-limit"
                        inputMode="decimal"
                        value={creditLimit}
                        onChange={(event) => setCreditLimit(event.target.value)}
                    />
                    <p className="text-[11px] text-ink-3">How far below zero the balance may go before calls stop.</p>
                </div>
            </div>
            <Button size="sm" onClick={() => void save()} disabled={saving}>
                Save plan and rates
            </Button>
        </Panel>
    );
}

/** Add or remove credit, with a reason (Stripe billing only). */
function CreditAdjustment({ detail, onSaved }: { detail: AdminOrganizationDetail; onSaved: () => void }) {
    const org = detail.organization;
    const [direction, setDirection] = useState<"add" | "remove">("add");
    const [amount, setAmount] = useState("");
    const [kind, setKind] = useState<"adjustment" | "refund">("adjustment");
    const [reason, setReason] = useState("");
    const [confirming, setConfirming] = useState(false);
    const [saving, setSaving] = useState(false);

    const valid = MONEY.test(amount.trim()) && Number(amount) > 0 && reason.trim().length > 0;
    const signed = `${direction === "remove" ? "-" : ""}${amount.trim()}`;

    const submit = async () => {
        setSaving(true);
        try {
            await platformAdminApi.adjustBalance(org.id, { entry_type: kind, amount_eur: signed, description: reason.trim() });
            toast.success(direction === "add" ? "Credit added" : "Credit removed");
            setAmount("");
            setReason("");
            onSaved();
        } catch (err) {
            toast.error(errorMessage(err, "Could not change the balance"));
        } finally {
            setSaving(false);
            setConfirming(false);
        }
    };

    return (
        <Panel className="space-y-3">
            <div>
                <PanelTitle as="h3">Add or remove credit</PanelTitle>
                <PanelDescription>Balance now {formatEur(org.balance_eur)}. Written to the ledger with your reason.</PanelDescription>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
                <div className="space-y-1.5">
                    <Label htmlFor="direction">Change</Label>
                    <Select value={direction} onValueChange={(value) => setDirection(value as "add" | "remove")}>
                        <SelectTrigger id="direction">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="add">Add credit</SelectItem>
                            <SelectItem value="remove">Remove credit</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="amount">Amount, EUR</Label>
                    <Input id="amount" inputMode="decimal" placeholder="20" value={amount} onChange={(event) => setAmount(event.target.value)} />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="kind">Ledger type</Label>
                    <Select value={kind} onValueChange={(value) => setKind(value as "adjustment" | "refund")}>
                        <SelectTrigger id="kind">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="adjustment">Adjustment</SelectItem>
                            <SelectItem value="refund">Refund</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="reason">Reason</Label>
                    <Input id="reason" maxLength={500} placeholder="e.g. Invoice INV-0042 paid" value={reason} onChange={(event) => setReason(event.target.value)} />
                </div>
            </div>
            <Button size="sm" disabled={!valid || saving} onClick={() => setConfirming(true)}>
                {direction === "add" ? "Add" : "Remove"} {valid ? formatEur(amount) : "credit"}
            </Button>
            <AlertDialog open={confirming} onOpenChange={setConfirming}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>
                            {direction === "add" ? "Add" : "Remove"} {formatEur(amount)} {direction === "add" ? "to" : "from"} {org.name || `workspace #${org.id}`}?
                        </AlertDialogTitle>
                        <AlertDialogDescription>Reason: {reason.trim()}. This is recorded in the ledger and the audit log.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction disabled={saving} onClick={() => void submit()}>
                            Confirm
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </Panel>
    );
}

function ConcurrencyLimit({ detail, onSaved }: { detail: AdminOrganizationDetail; onSaved: () => void }) {
    const org = detail.organization;
    const [value, setValue] = useState(String(org.concurrency_limit ?? ""));
    const [saving, setSaving] = useState(false);

    useEffect(() => setValue(String(org.concurrency_limit ?? "")), [org.concurrency_limit]);

    const save = async (limit: number | null) => {
        setSaving(true);
        try {
            await platformAdminApi.setConcurrencyLimit(org.id, limit);
            toast.success(limit === null ? "Back to the default limit" : `Limit set to ${limit}`);
            onSaved();
        } catch (err) {
            toast.error(errorMessage(err, "Could not change the limit"));
        } finally {
            setSaving(false);
        }
    };
    const parsed = Number(value);
    const valid = /^\d+$/.test(value.trim()) && parsed >= 1 && parsed <= 1000;

    return (
        <Panel className="space-y-3">
            <div>
                <PanelTitle as="h3">Calls at once</PanelTitle>
                <PanelDescription>
                    Now {org.effective_concurrency_limit}
                    {org.concurrency_limit === null ? " (the platform default)" : ""}. Applies from the next call.
                </PanelDescription>
            </div>
            <div className="flex flex-wrap items-end gap-2">
                <div className="space-y-1.5">
                    <Label htmlFor="concurrency">Limit (1–1000)</Label>
                    <Input id="concurrency" className="w-32" inputMode="numeric" value={value} onChange={(event) => setValue(event.target.value)} />
                </div>
                <Button size="sm" disabled={!valid || saving} onClick={() => void save(parsed)}>
                    Save limit
                </Button>
                {org.concurrency_limit !== null ? (
                    <Button size="sm" variant="outline" disabled={saving} onClick={() => void save(null)}>
                        Use the default
                    </Button>
                ) : null}
            </div>
        </Panel>
    );
}

function FeatureOverrides({ detail, onSaved }: { detail: AdminOrganizationDetail; onSaved: () => void }) {
    const org = detail.organization;
    const [saving, setSaving] = useState<string | null>(null);

    const change = async (feature: Feature, choice: string) => {
        const enabled = choice === "inherit" ? null : choice === "on";
        setSaving(feature);
        try {
            await platformAdminApi.setOrganizationFeature(feature, org.id, enabled);
            toast.success(`${FEATURE_LABELS[feature]} updated for this workspace`);
            onSaved();
        } catch (err) {
            toast.error(errorMessage(err, "Could not change the switch"));
        } finally {
            setSaving(null);
        }
    };

    return (
        <Panel className="space-y-3">
            <div>
                <PanelTitle as="h3">Features for this workspace</PanelTitle>
                <PanelDescription>Overrides the platform-wide switch (Features tab) for this workspace only.</PanelDescription>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
                {(Object.keys(FEATURES) as Feature[]).map((feature) => {
                    const override = detail.feature_overrides[feature];
                    const choice = override === undefined ? "inherit" : override ? "on" : "off";
                    return (
                        <div key={feature} className="space-y-1.5">
                            <Label htmlFor={`override-${feature}`}>
                                {FEATURE_LABELS[feature]}: {detail.features[feature] ? "shown" : "hidden"}
                            </Label>
                            <Select value={choice} disabled={saving === feature} onValueChange={(value) => void change(feature, value)}>
                                <SelectTrigger id={`override-${feature}`}>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="inherit">Follow the platform switch</SelectItem>
                                    <SelectItem value="on">On for this workspace</SelectItem>
                                    <SelectItem value="off">Off for this workspace</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                    );
                })}
            </div>
        </Panel>
    );
}

/** Platform admin > Organisations > one workspace. */
export default function PlatformAdminOrganizationPage() {
    const params = useParams<{ organizationId: string }>();
    const organizationId = Number(params.organizationId);
    const { config } = useAppConfig();
    const stripeBilling = config?.billingProvider === "stripe";
    const { data, error, reload } = useAdminData(() => platformAdminApi.organization(organizationId), [organizationId]);
    const audit = useAdminData(() => platformAdminApi.auditLog({ organization_id: organizationId, limit: 10 }), [organizationId]);
    const refresh = () => {
        void reload();
        void audit.reload();
    };

    if (!Number.isInteger(organizationId)) return <AdminError message="Unknown workspace" />;
    if (error) return <AdminError message={error} />;
    if (!data) return <AdminLoading />;
    const org = data.organization;

    return (
        <div className="space-y-6">
            <div className="space-y-1">
                <Link href="/superadmin/organizations" className="inline-flex items-center gap-1 text-xs text-ink-3 hover:text-foreground">
                    <ArrowLeft className="h-3.5 w-3.5" /> Organisations
                </Link>
                <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold">
                    {org.name || "Unnamed workspace"}
                    <span className="font-mono text-sm font-normal text-ink-3">#{org.id}</span>
                    <OrganizationStatus status={org.status} />
                </h1>
                <p className="text-xs text-ink-3">
                    Created {formatWhen(org.created_at)} · last call {formatWhen(org.last_call_at)}
                </p>
            </div>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                <StatTile label="Members" value={org.members_count} />
                <StatTile label="Plan" value={org.plan ? PLAN_LABELS[org.plan] ?? org.plan : "—"} />
                <StatTile label="Balance" value={formatEur(org.balance_eur)} />
                <StatTile
                    label="Per minute"
                    value={formatEur(org.effective_price_per_minute_eur)}
                    hint={org.price_per_minute_override_eur !== null ? "custom rate" : "plan rate"}
                />
                <StatTile label="Credit limit" value={formatEur(org.credit_limit_eur)} />
                <StatTile label="Calls at once" value={org.effective_concurrency_limit} hint={org.concurrency_limit === null ? "default" : "custom"} />
            </div>

            <section className="space-y-3">
                <SectionHeading>Billing</SectionHeading>
                {stripeBilling ? (
                    <>
                        <BillingTerms detail={data} onSaved={refresh} />
                        <CreditAdjustment detail={data} onSaved={refresh} />
                    </>
                ) : (
                    <p className="text-sm text-ink-2">
                        Billing is off on this deployment (BILLING_PROVIDER is {config?.billingProvider ?? "unknown"}), so plans,
                        rates and credit can&apos;t be changed here.
                    </p>
                )}
            </section>

            <section className="space-y-3">
                <SectionHeading>Limits and features</SectionHeading>
                <ConcurrencyLimit detail={data} onSaved={refresh} />
                <FeatureOverrides detail={data} onSaved={refresh} />
            </section>

            <section className="space-y-3">
                <SectionHeading>Members</SectionHeading>
                {data.members.length === 0 ? (
                    <p className="text-sm text-ink-3">No members.</p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Email</TableHead>
                                <TableHead>Name</TableHead>
                                <TableHead>Role</TableHead>
                                <TableHead>Email verified</TableHead>
                                <TableHead>Joined</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.members.map((member) => (
                                <TableRow key={member.user_id}>
                                    <TableCell>
                                        <Link className="hover:underline" href={`/superadmin/users?search=${encodeURIComponent(member.email ?? String(member.user_id))}`}>
                                            {member.email || `User #${member.user_id}`}
                                        </Link>
                                        {member.is_platform_admin ? <StatusPill tone="warn" className="ml-2">Platform admin</StatusPill> : null}
                                    </TableCell>
                                    <TableCell>{member.name || "—"}</TableCell>
                                    <TableCell className="capitalize">{member.role}</TableCell>
                                    <TableCell>{member.email_verified ? "Yes" : "No"}</TableCell>
                                    <TableCell className="whitespace-nowrap text-xs">{formatWhen(member.joined_at)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </section>

            <section className="space-y-3">
                <SectionHeading>Recent calls</SectionHeading>
                <RunsTable runs={data.recent_calls} />
            </section>

            {data.ledger ? (
                <section className="space-y-3">
                    <SectionHeading action={<span className="font-mono text-xs text-ink-3">newest {data.ledger.length} of {data.ledger_total}</span>}>
                        Billing ledger
                    </SectionHeading>
                    {data.ledger.length === 0 ? (
                        <p className="text-sm text-ink-3">No ledger entries.</p>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>When</TableHead>
                                    <TableHead>Type</TableHead>
                                    <TableHead className="text-right">Amount</TableHead>
                                    <TableHead className="text-right">Balance after</TableHead>
                                    <TableHead>Description</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {data.ledger.map((entry) => (
                                    <TableRow key={entry.id}>
                                        <TableCell className="whitespace-nowrap text-xs">{formatWhen(entry.created_at)}</TableCell>
                                        <TableCell className="font-mono text-xs">{entry.entry_type}</TableCell>
                                        <TableCell className="text-right tabular-nums">{formatEur(entry.amount_eur, 4)}</TableCell>
                                        <TableCell className="text-right tabular-nums">{formatEur(entry.balance_after_eur)}</TableCell>
                                        <TableCell className="text-xs">
                                            {entry.description || "—"}
                                            {entry.workflow_run_id ? <span className="text-ink-3"> · run #{entry.workflow_run_id}</span> : null}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                </section>
            ) : null}

            <section className="space-y-3">
                <SectionHeading
                    action={
                        <Link className="text-xs text-ink-3 hover:text-foreground" href={`/superadmin/audit?organization_id=${org.id}`}>
                            All changes
                        </Link>
                    }
                >
                    Admin changes to this workspace
                </SectionHeading>
                {audit.data && audit.data.entries.length > 0 ? (
                    <ul className="space-y-1 text-xs">
                        {audit.data.entries.map((entry) => (
                            <li key={entry.id}>
                                <span className="text-ink-3">{formatWhen(entry.created_at)}</span> ·{" "}
                                {AUDIT_ACTION_LABELS[entry.action] ?? entry.action} by {entry.actor_email ?? `user #${entry.actor_user_id ?? "?"}`}
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-xs text-ink-3">{audit.error ?? "None yet."}</p>
                )}
            </section>
        </div>
    );
}
