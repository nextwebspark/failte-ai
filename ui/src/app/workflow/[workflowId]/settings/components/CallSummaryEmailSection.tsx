import { Mail } from "lucide-react";
import { useState } from "react";

import type { CallSummaryEmailConfiguration } from "@/client/types.gen";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useUnsavedChanges } from "@/context/UnsavedChangesContext";
import { useAuth } from "@/lib/auth";
import { signedInEmail } from "@/lib/auth/identity";

import { SettingRow, SettingsSection } from "../SettingsLayout";
import { useSettingsSection } from "../SettingsSaveBar";

/** Mirrors MAX_CALL_SUMMARY_RECIPIENTS in api/schemas/call_summary_email.py. */
export const MAX_CALL_SUMMARY_RECIPIENTS = 5;

const ADDRESS = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The addresses in a comma-separated list, without blanks. */
export function parseRecipients(text: string): string[] {
    return text.split(/[,;\s]+/).filter(Boolean);
}

/** What to save. While off, the box is hidden and its unchecked contents must
 * not block the save, so only the usable addresses are kept. */
export function savedRecipients(enabled: boolean, recipients: string[]): string[] {
    return enabled
        ? recipients
        : recipients.filter((address) => ADDRESS.test(address)).slice(0, MAX_CALL_SUMMARY_RECIPIENTS);
}

/** Why the setting can't be saved as it is, or null when it can. */
export function callSummaryProblem(enabled: boolean, recipients: string[]): string | null {
    if (!enabled) return null;
    if (recipients.length === 0) return "Add an email address for call summaries";
    if (recipients.length > MAX_CALL_SUMMARY_RECIPIENTS) {
        return `Send call summaries to at most ${MAX_CALL_SUMMARY_RECIPIENTS} addresses`;
    }
    if (recipients.some((address) => !ADDRESS.test(address))) return "Check the call summary email addresses";
    return null;
}

export function CallSummaryEmailSection({ saved }: { saved: CallSummaryEmailConfiguration | undefined }) {
    const { user } = useAuth();
    const savedEnabled = saved?.enabled ?? false;
    const savedText = (saved?.recipients ?? []).join(", ");
    const [enabled, setEnabled] = useState(savedEnabled);
    const [text, setText] = useState(savedText);
    const recipients = parseRecipients(text);
    const isDirty = enabled !== savedEnabled || recipients.join(", ") !== savedText;

    useUnsavedChanges("summaries", isDirty);
    useSettingsSection("summaries", {
        label: "Call summaries",
        dirty: isDirty,
        blocker: callSummaryProblem(enabled, recipients),
        patch: () => ({
            configurations: { call_summary_email: { enabled, recipients: savedRecipients(enabled, recipients) } },
        }),
        afterSave: () => setText(savedRecipients(enabled, recipients).join(", ")),
    });

    const toggle = (next: boolean) => {
        setEnabled(next);
        // Turning it on for the first time starts from the user's own address.
        if (next && !text.trim()) setText(signedInEmail(user) ?? "");
    };

    return (
        <SettingsSection
            id="summaries"
            icon={Mail}
            tone="sky"
            title="Call summaries"
            description="An email after each phone call where the agent takes a message or books or cancels an appointment."
        >
            <SettingRow
                compact
                label="Email call summaries"
                htmlFor="call-summary-enabled"
                hint="The caller's name, number and reason, any booking, and a link to the call."
            >
                <Switch id="call-summary-enabled" checked={enabled} onCheckedChange={toggle} />
            </SettingRow>
            {enabled && (
                <SettingRow
                    label="Send to"
                    htmlFor="call-summary-recipients"
                    hint={`Up to ${MAX_CALL_SUMMARY_RECIPIENTS} addresses, separated by commas.`}
                >
                    <Input
                        id="call-summary-recipients"
                        type="text"
                        inputMode="email"
                        autoComplete="email"
                        placeholder="you@example.com"
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                    />
                </SettingRow>
            )}
        </SettingsSection>
    );
}
