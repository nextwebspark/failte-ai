"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    getTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsGet,
    updateTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsPut,
} from "@/client/sdk.gen";
import type { LinesBusyAction, TransferSettings, UpdateTransferSettingsRequest } from "@/client/types.gen";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { TransferNumberHint } from "@/components/workflow/TransferNumberHint";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { LINES_BUSY_OPTIONS, linesBusyNote, staffPhoneLine, transferHint, useTransferNumberCheck } from "@/lib/transferNumber";

/**
 * Under "Pass calls to your team": the live check of the typed number
 * ("✓ Irish mobile · saved as +353 87 123 4567", why it can't be used, or
 * the demo-number warning) and "Show the caller's number when we pass a call
 * to you", with what the staff phone will actually show, and "When all lines
 * are busy" (what happens to a caller who rings while every line is in use).
 */
export function TransferOptions({
    workflowId,
    value,
    disabled,
}: {
    workflowId: number;
    value: string;
    disabled: boolean;
}) {
    const hint = transferHint(useTransferNumberCheck(value, workflowId));
    const { can } = useOrgConfig();
    const [settings, setSettings] = useState<TransferSettings | null>(null);
    const [switching, setSwitching] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await getTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsGet({
                path: { workflow_id: workflowId },
            });
            setSettings(res.data ?? null);
        } catch {
            setSettings(null);
        }
    }, [workflowId]);

    useEffect(() => {
        void load();
    }, [load]);

    const save = async (body: UpdateTransferSettingsRequest) => {
        setSwitching(true);
        try {
            const res = await updateTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsPut({
                path: { workflow_id: workflowId },
                body,
            });
            if (res.error || !res.data) {
                toast.error(detailFromError(res.error, "Couldn't change the setting. Please try again."));
                return;
            }
            setSettings(res.data);
        } catch {
            toast.error("Couldn't change the setting. Please try again.");
        } finally {
            setSwitching(false);
        }
    };

    return (
        <>
            <TransferNumberHint id="transfer-number-check" hint={hint} />
            {settings && value.trim() && (
                <div className="mt-3 flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-3">
                        <label id="show-caller-number" className="text-caption font-medium text-foreground">
                            Show the caller&apos;s number when we pass a call to you
                        </label>
                        <Switch
                            aria-labelledby="show-caller-number"
                            checked={settings.show_caller_number}
                            disabled={disabled || switching || !can("agents:facts")}
                            onCheckedChange={(checked) => void save({ show_caller_number: checked })}
                        />
                    </div>
                    <p className="text-caption leading-relaxed text-ink-3">{staffPhoneLine(settings)}</p>
                </div>
            )}
            {settings && (
                <fieldset className="mt-4 flex flex-col gap-1.5" disabled={disabled || switching || !can("agents:facts")}>
                    <legend id="lines-busy" className="text-caption font-medium text-foreground">
                        When all lines are busy
                    </legend>
                    <RadioGroup
                        aria-labelledby="lines-busy"
                        value={settings.lines_busy ?? "voicemail"}
                        onValueChange={(next) => void save({ lines_busy: next as LinesBusyAction })}
                        className="mt-1 gap-2"
                    >
                        {LINES_BUSY_OPTIONS.map((option) => {
                            const id = `lines-busy-${option.value}`;
                            return (
                                <div key={option.value} className="flex items-start gap-2">
                                    <RadioGroupItem value={option.value} id={id} className="mt-0.5" />
                                    <label htmlFor={id} className="text-caption leading-snug">
                                        <span className="font-medium text-foreground">{option.label}</span>
                                        <span className="block text-ink-3">{option.help}</span>
                                    </label>
                                </div>
                            );
                        })}
                    </RadioGroup>
                    {linesBusyNote(settings, value) ? (
                        <p className="text-caption leading-relaxed text-ink-3">{linesBusyNote(settings, value)}</p>
                    ) : null}
                </fieldset>
            )}
        </>
    );
}
