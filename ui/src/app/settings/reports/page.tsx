"use client";

import { CalendarDays, Eye, Mail, Send, Users, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    addEmailReportRecipientApiV1OrganizationsEmailReportsRecipientsPost,
    getEmailReportSettingsApiV1OrganizationsEmailReportsGet,
    previewEmailReportApiV1OrganizationsEmailReportsPreviewGet,
    removeEmailReportRecipientApiV1OrganizationsEmailReportsRecipientsRecipientIdDelete,
    resendEmailReportConfirmationApiV1OrganizationsEmailReportsRecipientsRecipientIdResendPost,
    sendTestEmailReportApiV1OrganizationsEmailReportsTestPost,
    updateEmailReportSettingsApiV1OrganizationsEmailReportsPut,
} from "@/client/sdk.gen";
import type { EmailReportSettingsResponse, EmailReportSettingsUpdate, ReportRecipientView } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import { SettingBlock, SettingsSection } from "@/components/settings/SettingsLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { addressProblem, describe, FREQUENCIES, type ReportFrequency, sentLabel, TITLES, zoneLabel } from "./reportCopy";

const ALL_AGENTS = "all";

function updateOf(data: EmailReportSettingsResponse): EmailReportSettingsUpdate {
    return {
        daily: data.daily,
        weekly: data.weekly,
        monthly: data.monthly,
        daily_send_time: data.daily_send_time,
        workflow_id: data.workflow_id ?? null,
    };
}

/**
 * Settings > Reports by email. Owners and admins choose which call reports
 * are emailed (daily, weekly, monthly), when, for which agent and to whom.
 * Everyone who reads reports can see the settings, preview the email and
 * send themselves a test.
 */
export default function ReportsByEmailPage() {
    const { can, role, loading: orgLoading } = useOrgConfig();
    const { user, loading: authLoading } = useAuth();
    const allowed = can("reports:read");
    const fetched = useRef(false);
    const [data, setData] = useState<EmailReportSettingsResponse | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (authLoading || !user || !allowed || fetched.current) return;
        fetched.current = true;
        void getEmailReportSettingsApiV1OrganizationsEmailReportsGet().then((result) => {
            if (result.error || !result.data) setLoadFailed(true);
            else setData(result.data);
        });
    }, [authLoading, user, allowed]);

    if (!orgLoading && role !== null && !allowed) return <NoAccess role={role} />;

    if (loadFailed) {
        return (
            <div className="page-body">
                <p className="text-sm text-danger" role="alert">
                    Couldn&apos;t load the report settings. Refresh to try again.
                </p>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="page-body" aria-busy="true">
                <div className="flex w-full flex-col gap-[18px]">
                    <Skeleton className="h-44 w-full" />
                    <Skeleton className="h-40 w-full" />
                    <Skeleton className="h-28 w-full" />
                </div>
            </div>
        );
    }

    const editable = data.can_edit;

    async function save(next: EmailReportSettingsUpdate) {
        if (!data) return;
        const previous = data;
        setData({ ...data, ...next });
        setSaving(true);
        const result = await updateEmailReportSettingsApiV1OrganizationsEmailReportsPut({ body: next });
        setSaving(false);
        if (result.error || !result.data) {
            setData(previous);
            toast.error(detailFromError(result.error, "Couldn't save. Try again."));
            return;
        }
        setData(result.data);
        toast.success("Saved");
    }

    return (
        <div className="page-body">
            <div className="flex w-full flex-col gap-[18px]">
                {!editable && (
                    <p className="rounded-lg border border-line bg-panel-2 px-4 py-3 text-[13px] text-ink-2" role="status">
                        You can see these settings, preview the email and send yourself a test. Only the
                        workspace owner or an admin can change who gets reports.
                    </p>
                )}
                {!data.email_available && (
                    <p className="rounded-lg bg-amber-dim px-4 py-3 text-[13px] text-amber" role="status">
                        Email isn&apos;t set up on this server yet, so nothing is sent for now.
                    </p>
                )}

                <WhichReports data={data} editable={editable} saving={saving} onSave={save} />
                <Recipients data={data} editable={editable} onChange={setData} />
                <PreviewAndTest data={data} ownEmail={data.your_email ?? null} />
            </div>
        </div>
    );
}

function WhichReports({
    data,
    editable,
    saving,
    onSave,
}: {
    data: EmailReportSettingsResponse;
    editable: boolean;
    saving: boolean;
    onSave: (next: EmailReportSettingsUpdate) => Promise<void>;
}) {
    const current = updateOf(data);
    const [time, setTime] = useState(data.daily_send_time);
    useEffect(() => setTime(data.daily_send_time), [data.daily_send_time]);
    const agents = data.agents ?? [];

    function commitTime() {
        if (/^([01]\d|2[0-3]):[0-5]\d$/.test(time) && time !== data.daily_send_time) {
            void onSave({ ...current, daily_send_time: time });
        } else {
            setTime(data.daily_send_time);
        }
    }

    return (
        <SettingsSection
            id="which"
            icon={CalendarDays}
            tone="brand"
            title="Which reports"
            description={`A summary of your calls: how many, how they went and who needs a call back. Times are ${zoneLabel(data.timezone)}.`}
        >
            <SettingBlock>
                <ul className="grid gap-3 @2xl:grid-cols-3" aria-label="Reports">
                    {FREQUENCIES.map((frequency) => {
                        const on = data[frequency];
                        const { covers, arrives } = describe(frequency, data.daily_send_time);
                        const last = sentLabel(frequency, data.last_sent?.[frequency]);
                        const id = `report-${frequency}`;
                        return (
                            <li
                                key={frequency}
                                className={cn(
                                    "flex flex-col gap-2 rounded-lg border p-3.5",
                                    on ? "border-brand bg-brand-dim" : "border-line bg-panel",
                                )}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <label htmlFor={id} className="text-[14px] font-semibold text-foreground">
                                        {TITLES[frequency]}
                                    </label>
                                    <Switch
                                        id={id}
                                        checked={on}
                                        disabled={!editable || saving}
                                        aria-describedby={`${id}-about`}
                                        onCheckedChange={(value) => void onSave({ ...current, [frequency]: value })}
                                    />
                                </div>
                                <p id={`${id}-about`} className="text-[12.5px] leading-relaxed text-ink-2">
                                    {covers} <span className="text-ink-3">Arrives: {arrives}</span>
                                </p>
                                {frequency === "daily" && (
                                    <div className="flex items-center gap-2">
                                        <label htmlFor="daily-time" className="text-[12.5px] text-ink-2">
                                            Send at
                                        </label>
                                        <Input
                                            id="daily-time"
                                            type="time"
                                            step={900}
                                            value={time}
                                            disabled={!editable || saving}
                                            onChange={(e) => setTime(e.target.value)}
                                            onBlur={commitTime}
                                            onKeyDown={(e) => {
                                                if (e.key === "Enter") commitTime();
                                            }}
                                            className="h-8 w-[120px] bg-panel"
                                        />
                                    </div>
                                )}
                                {last && <p className="text-[11.5px] text-ink-3">Last sent: {last}</p>}
                            </li>
                        );
                    })}
                </ul>
                {agents.length > 1 && (
                    <div className="flex flex-col gap-1.5 @lg:flex-row @lg:items-center @lg:gap-3">
                        <span id="report-agent-label" className="text-[13px] font-semibold text-foreground">
                            Calls to
                        </span>
                        <Select
                            value={data.workflow_id ? String(data.workflow_id) : ALL_AGENTS}
                            disabled={!editable || saving}
                            onValueChange={(value) =>
                                void onSave({ ...current, workflow_id: value === ALL_AGENTS ? null : Number(value) })
                            }
                        >
                            <SelectTrigger className="w-full bg-panel @lg:w-[240px]" aria-labelledby="report-agent-label">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value={ALL_AGENTS}>All agents</SelectItem>
                                {agents.map((agent) => (
                                    <SelectItem key={agent.id} value={String(agent.id)}>
                                        {agent.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                )}
            </SettingBlock>
        </SettingsSection>
    );
}

function Recipients({
    data,
    editable,
    onChange,
}: {
    data: EmailReportSettingsResponse;
    editable: boolean;
    onChange: (data: EmailReportSettingsResponse) => void;
}) {
    const [address, setAddress] = useState("");
    const [problem, setProblem] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const recipients = data.recipients ?? [];
    const addresses = recipients.map((r) => r.email);
    const own = data.own_email ?? null;
    const ownListed = own !== null && addresses.some((a) => a.toLowerCase() === own.toLowerCase());
    const full = recipients.length >= data.max_recipients;

    async function add(email: string): Promise<boolean> {
        setBusy("add");
        const result = await addEmailReportRecipientApiV1OrganizationsEmailReportsRecipientsPost({ body: { email } });
        setBusy(null);
        if (result.error || !result.data) {
            toast.error(detailFromError(result.error, "Couldn't add that address. Try again."));
            return false;
        }
        onChange(result.data.settings);
        const added = result.data.recipient;
        if (added.status === "active") toast.success(`${added.email} will get the reports.`);
        else if (result.data.confirmation_sent)
            toast.success(`We've emailed ${added.email} a link. Nothing is sent until they confirm.`);
        else toast.warning(`Added ${added.email}, but the confirmation email couldn't be sent. Try Resend.`);
        return true;
    }

    async function addOther(event: FormEvent) {
        event.preventDefault();
        const found = addressProblem(address, addresses, data.max_recipients);
        setProblem(found);
        if (found) return;
        if (await add(address.trim())) setAddress("");
    }

    async function resend(recipient: ReportRecipientView) {
        setBusy(recipient.id);
        const result = await resendEmailReportConfirmationApiV1OrganizationsEmailReportsRecipientsRecipientIdResendPost({
            path: { recipient_id: recipient.id },
        });
        setBusy(null);
        if (result.error || !result.data) {
            toast.error(detailFromError(result.error, "Couldn't resend. Try again."));
            return;
        }
        onChange(result.data);
        toast.success(`Sent a new link to ${recipient.email}.`);
    }

    async function remove(recipient: ReportRecipientView) {
        setBusy(recipient.id);
        const result = await removeEmailReportRecipientApiV1OrganizationsEmailReportsRecipientsRecipientIdDelete({
            path: { recipient_id: recipient.id },
        });
        setBusy(null);
        if (result.error || !result.data) {
            toast.error(detailFromError(result.error, "Couldn't remove. Try again."));
            return;
        }
        onChange(result.data);
        toast.success(`${recipient.email} won't get reports any more.`);
    }

    return (
        <SettingsSection
            id="recipients"
            icon={Users}
            tone="sky"
            title="Who gets them"
            description="Your own sign-in address starts straight away. Anyone else confirms from a link first."
        >
            <SettingBlock>
                {recipients.length === 0 ? (
                    <p className="text-[13px] text-ink-2">Nobody yet. Add an address to start getting reports.</p>
                ) : (
                    <ul className="flex flex-col divide-y divide-line-soft rounded-lg border border-line" aria-label="Recipients">
                        {recipients.map((recipient) => (
                            <li key={recipient.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5">
                                <span className="min-w-0 flex-1 break-all text-[13.5px] text-foreground">{recipient.email}</span>
                                {recipient.status === "active" ? (
                                    <StatusPill tone="ok">Getting reports</StatusPill>
                                ) : (
                                    <StatusPill tone="warn">Waiting for confirmation</StatusPill>
                                )}
                                {editable && (
                                    <span className="flex items-center gap-1">
                                        {recipient.status === "pending" && (
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="sm"
                                                disabled={busy !== null}
                                                onClick={() => void resend(recipient)}
                                            >
                                                Resend
                                            </Button>
                                        )}
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            aria-label={`Remove ${recipient.email}`}
                                            disabled={busy !== null}
                                            onClick={() => void remove(recipient)}
                                        >
                                            <X className="size-3.5" aria-hidden />
                                            Remove
                                        </Button>
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                )}

                {editable && !full && (
                    <div className="flex flex-col gap-3">
                        {own && !ownListed && (
                            <Button
                                type="button"
                                variant="outline"
                                className="self-start"
                                disabled={busy !== null}
                                onClick={() => void add(own)}
                            >
                                <Mail className="size-3.5" aria-hidden />
                                <span className="break-all text-left">Add my email ({own})</span>
                            </Button>
                        )}
                        <form className="flex flex-col gap-1.5" onSubmit={addOther} noValidate>
                            <label htmlFor="report-address" className="text-[13px] font-semibold text-foreground">
                                Add another email
                            </label>
                            <div className="flex flex-wrap gap-2">
                                <Input
                                    id="report-address"
                                    type="email"
                                    autoComplete="email"
                                    placeholder="name@example.com"
                                    value={address}
                                    aria-invalid={problem !== null}
                                    aria-describedby={problem ? "report-address-problem" : "report-address-hint"}
                                    onChange={(e) => {
                                        setAddress(e.target.value);
                                        setProblem(null);
                                    }}
                                    className="min-w-0 flex-1 basis-56 bg-panel"
                                />
                                <Button type="submit" variant="outline" disabled={busy !== null}>
                                    {busy === "add" ? "Adding…" : "Add"}
                                </Button>
                            </div>
                            {problem ? (
                                <p id="report-address-problem" className="text-xs text-danger" role="alert">
                                    {problem}
                                </p>
                            ) : (
                                <p id="report-address-hint" className="text-xs text-ink-3">
                                    We&apos;ll email them a link to confirm. It works for 48 hours.
                                </p>
                            )}
                        </form>
                    </div>
                )}
                {editable && full && (
                    <p className="text-xs text-ink-3">That&apos;s the most addresses you can add ({data.max_recipients}).</p>
                )}
            </SettingBlock>
        </SettingsSection>
    );
}

function PreviewAndTest({ data, ownEmail }: { data: EmailReportSettingsResponse; ownEmail: string | null }) {
    const [frequency, setFrequency] = useState<ReportFrequency>("daily");
    const [html, setHtml] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [failed, setFailed] = useState(false);
    const [sending, setSending] = useState(false);

    async function preview(which: ReportFrequency) {
        setFrequency(which);
        setLoading(true);
        setFailed(false);
        const result = await previewEmailReportApiV1OrganizationsEmailReportsPreviewGet({
            query: { frequency: which },
            parseAs: "text",
        });
        setLoading(false);
        if (result.error || typeof result.data !== "string") {
            setFailed(true);
            setHtml(null);
            return;
        }
        setHtml(result.data);
    }

    async function sendTest() {
        setSending(true);
        const result = await sendTestEmailReportApiV1OrganizationsEmailReportsTestPost({ body: { frequency } });
        setSending(false);
        if (result.error || !result.data) {
            toast.error(detailFromError(result.error, "Couldn't send the test. Try again."));
            return;
        }
        toast.success(`Sent a test ${frequency} report to ${result.data.sent_to}.`);
    }

    return (
        <SettingsSection
            id="preview"
            icon={Eye}
            tone="mute"
            title="Preview"
            description="See the email with your real calls: today so far for daily, the last full week or month otherwise."
        >
            <SettingBlock>
                <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Which report to preview">
                    {FREQUENCIES.map((which) => (
                        <Button
                            key={which}
                            type="button"
                            variant={html !== null && frequency === which ? "default" : "outline"}
                            size="sm"
                            aria-pressed={html !== null && frequency === which}
                            disabled={loading}
                            onClick={() => void preview(which)}
                        >
                            {TITLES[which]}
                        </Button>
                    ))}
                </div>
                {loading && <Skeleton className="h-[420px] w-full" />}
                {failed && (
                    <p className="text-[13px] text-danger" role="alert">
                        Couldn&apos;t make the preview. Try again.
                    </p>
                )}
                {!loading && html !== null && (
                    <iframe
                        title={`Preview of the ${frequency} report email`}
                        srcDoc={html}
                        sandbox=""
                        className="h-[900px] w-full rounded-lg border border-line bg-white"
                    />
                )}
                <div className="flex flex-col gap-1.5 border-t border-line-soft pt-3.5">
                    <Button
                        type="button"
                        className="self-start"
                        disabled={sending || !data.email_available || !ownEmail}
                        onClick={() => void sendTest()}
                    >
                        <Send className="size-3.5" aria-hidden />
                        {sending ? "Sending…" : `Send me a test now (${TITLES[frequency].toLowerCase()})`}
                    </Button>
                    <p className="text-xs text-ink-3">
                        {ownEmail ? `Goes only to ${ownEmail}.` : "Your account has no email address."}
                    </p>
                </div>
            </SettingBlock>
        </SettingsSection>
    );
}
