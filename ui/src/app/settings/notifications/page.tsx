"use client";

import { Mail, MessageSquare, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getNotificationSettingsApiV1OrganizationsNotificationsGet,
    updateNotificationSettingsApiV1OrganizationsNotificationsPut,
} from "@/client/sdk.gen";
import type { CallNotificationSettings, CallNotificationSettingsResponse } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import { SettingBlock, SettingRow, SettingsSection } from "@/components/settings/SettingsLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";

const MAX_EXTRA_RECIPIENTS = 10;
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Toggle = keyof Pick<
    CallNotificationSettings,
    | "email_enabled"
    | "email_on_booking"
    | "email_on_message"
    | "email_on_missed_call"
    | "email_members"
    | "text_caller_booking_confirmation"
>;

function settingsOf(response: CallNotificationSettingsResponse): CallNotificationSettings {
    return {
        email_enabled: response.email_enabled ?? true,
        email_on_booking: response.email_on_booking ?? true,
        email_on_message: response.email_on_message ?? true,
        email_on_missed_call: response.email_on_missed_call ?? true,
        email_members: response.email_members ?? true,
        extra_recipients: response.extra_recipients ?? [],
        text_caller_booking_confirmation: response.text_caller_booking_confirmation ?? true,
    };
}

function errorMessage(error: unknown): string {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
    return "Couldn't save. Try again.";
}

function ToggleRow({
    id,
    label,
    hint,
    checked,
    disabled,
    onChange,
}: {
    id: string;
    label: string;
    hint?: string;
    checked: boolean;
    disabled?: boolean;
    onChange: (value: boolean) => void;
}) {
    return (
        <SettingRow label={label} htmlFor={id} hint={hint} compact>
            <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
        </SettingRow>
    );
}

/**
 * Settings > Notifications. Owners and admins choose which calls are emailed
 * to the business, to whom, and whether callers are texted a booking
 * confirmation. Every change saves straight away.
 */
export default function NotificationsSettingsPage() {
    const { can, role, loading: orgLoading } = useOrgConfig();
    const { user, loading: authLoading } = useAuth();
    const allowed = can("notifications:manage");
    const fetched = useRef(false);
    const [data, setData] = useState<CallNotificationSettingsResponse | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [saving, setSaving] = useState(false);
    const [newAddress, setNewAddress] = useState("");

    useEffect(() => {
        if (authLoading || !user || !allowed || fetched.current) return;
        fetched.current = true;
        void getNotificationSettingsApiV1OrganizationsNotificationsGet().then((result) => {
            if (result.error || !result.data) setLoadFailed(true);
            else setData(result.data);
        });
    }, [authLoading, user, allowed]);

    if (!orgLoading && role !== null && !allowed) {
        return <NoAccess role={role} />;
    }

    async function save(next: CallNotificationSettings): Promise<boolean> {
        if (!data) return false;
        const previous = data;
        setData({ ...data, ...next });
        setSaving(true);
        const result = await updateNotificationSettingsApiV1OrganizationsNotificationsPut({ body: next });
        setSaving(false);
        if (result.error || !result.data) {
            setData(previous);
            toast.error(errorMessage(result.error));
            return false;
        }
        setData(result.data);
        return true;
    }

    function setToggle(key: Toggle, value: boolean) {
        if (data) void save({ ...settingsOf(data), [key]: value });
    }

    async function addAddress(event: FormEvent) {
        event.preventDefault();
        if (!data) return;
        const address = newAddress.trim();
        if (!EMAIL_SHAPE.test(address)) {
            toast.error("That doesn't look like an email address.");
            return;
        }
        const current = settingsOf(data);
        if (current.extra_recipients?.some((a) => a.toLowerCase() === address.toLowerCase())) {
            setNewAddress("");
            return;
        }
        if (await save({ ...current, extra_recipients: [...(current.extra_recipients ?? []), address] })) {
            setNewAddress("");
        }
    }

    function removeAddress(address: string) {
        if (!data) return;
        const current = settingsOf(data);
        void save({
            ...current,
            extra_recipients: (current.extra_recipients ?? []).filter((a) => a !== address),
        });
    }

    if (loadFailed) {
        return (
            <div className="page-body">
                <p className="text-sm text-danger" role="alert">
                    Couldn&apos;t load the notification settings. Refresh to try again.
                </p>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="page-body">
                <div className="flex w-full flex-col gap-[18px]">
                    <Skeleton className="h-64 w-full" />
                    <Skeleton className="h-28 w-full" />
                </div>
            </div>
        );
    }

    const settings = settingsOf(data);
    const emailOff = !settings.email_enabled;
    const members = data.member_recipients ?? [];
    const extras = settings.extra_recipients ?? [];

    return (
        <div className="page-body">
            <div className="flex w-full flex-col gap-[18px]">
                <SettingsSection
                    id="emails"
                    icon={Mail}
                    tone="brand"
                    title="Emails after calls"
                    description="One short email per call, with a link to the call."
                >
                    {!data.email_available && (
                        <SettingBlock>
                            <p className="text-caption text-amber" role="status">
                                Email isn&apos;t set up on this server yet, so nothing is sent for now.
                            </p>
                        </SettingBlock>
                    )}
                    <ToggleRow
                        id="email-enabled"
                        label="Email us after calls"
                        checked={settings.email_enabled ?? true}
                        disabled={saving}
                        onChange={(v) => setToggle("email_enabled", v)}
                    />
                    <ToggleRow
                        id="email-booking"
                        label="When a booking is made, moved or cancelled"
                        hint="Only changes the calendar confirmed."
                        checked={settings.email_on_booking ?? true}
                        disabled={saving || emailOff}
                        onChange={(v) => setToggle("email_on_booking", v)}
                    />
                    <ToggleRow
                        id="email-message"
                        label="When a message is taken"
                        hint="The caller left their name, number or reason, or asked for a booking the agent couldn't make."
                        checked={settings.email_on_message ?? true}
                        disabled={saving || emailOff}
                        onChange={(v) => setToggle("email_on_message", v)}
                    />
                    <ToggleRow
                        id="email-missed"
                        label="When a call is missed"
                        hint="The caller hung up straight away or without speaking, nobody picked up a transfer, or the call dropped."
                        checked={settings.email_on_missed_call ?? true}
                        disabled={saving || emailOff}
                        onChange={(v) => setToggle("email_on_missed_call", v)}
                    />
                    <ToggleRow
                        id="email-members"
                        label="Send to owners and admins"
                        hint={members.length ? members.join(", ") : "Nobody in this workspace is an owner or admin yet."}
                        checked={settings.email_members ?? true}
                        disabled={saving || emailOff}
                        onChange={(v) => setToggle("email_members", v)}
                    />
                    <SettingBlock>
                        <p className="text-caption font-semibold text-foreground">Also send to</p>
                        {extras.length > 0 && (
                            <ul className="flex flex-wrap gap-2" aria-label="Also send to">
                                {extras.map((address) => (
                                    <li
                                        key={address}
                                        className="flex items-center gap-1 rounded-md border border-line bg-panel-2 py-1 pl-2.5 pr-1 text-caption"
                                    >
                                        {address}
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon"
                                            className="size-6"
                                            aria-label={`Remove ${address}`}
                                            disabled={saving || emailOff}
                                            onClick={() => removeAddress(address)}
                                        >
                                            <X className="h-3.5 w-3.5" aria-hidden />
                                        </Button>
                                    </li>
                                ))}
                            </ul>
                        )}
                        {extras.length < MAX_EXTRA_RECIPIENTS ? (
                            <form className="flex gap-2" onSubmit={addAddress} noValidate>
                                <Input
                                    type="email"
                                    aria-label="Email address to add"
                                    placeholder="name@example.com"
                                    value={newAddress}
                                    disabled={saving || emailOff}
                                    onChange={(e) => setNewAddress(e.target.value)}
                                    className="max-w-xs"
                                />
                                <Button type="submit" variant="outline" disabled={saving || emailOff || !newAddress.trim()}>
                                    Add
                                </Button>
                            </form>
                        ) : (
                            <p className="text-xs text-ink-3">That&apos;s the most addresses you can add.</p>
                        )}
                    </SettingBlock>
                </SettingsSection>

                <SettingsSection
                    id="texts"
                    icon={MessageSquare}
                    tone="sky"
                    title="Texts to callers"
                    description="A text confirming the booking, with the day, time and your number."
                >
                    <ToggleRow
                        id="text-booking"
                        label="Text callers a booking confirmation"
                        hint="Only when the calendar confirmed the booking, and only to mobile numbers."
                        checked={settings.text_caller_booking_confirmation ?? true}
                        disabled={saving}
                        onChange={(v) => setToggle("text_caller_booking_confirmation", v)}
                    />
                    {!data.sms_available && (
                        <SettingBlock>
                            <p className="text-caption text-ink-2" role="status">
                                Texting isn&apos;t set up yet. Once it is, confirmations start on their own if
                                this is on.
                            </p>
                        </SettingBlock>
                    )}
                </SettingsSection>
            </div>
        </div>
    );
}
