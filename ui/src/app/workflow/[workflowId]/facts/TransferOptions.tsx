"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    getTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsGet,
    updateTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsPut,
} from "@/client/sdk.gen";
import type { TransferSettings } from "@/client/types.gen";
import { Switch } from "@/components/ui/switch";
import { TransferNumberHint } from "@/components/workflow/TransferNumberHint";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { staffPhoneLine, transferHint, useTransferNumberCheck } from "@/lib/transferNumber";

/**
 * Under "Pass calls to your team": the live check of the typed number
 * ("✓ Irish mobile · saved as +353 87 123 4567", why it can't be used, or
 * the demo-number warning) and "Show the caller's number when we pass a call
 * to you", with what the staff phone will actually show.
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

    const setShowCaller = async (show: boolean) => {
        setSwitching(true);
        try {
            const res = await updateTransferSettingsApiV1WorkflowWorkflowIdTransferSettingsPut({
                path: { workflow_id: workflowId },
                body: { show_caller_number: show },
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
                        <label id="show-caller-number" className="text-[13px] font-medium text-foreground">
                            Show the caller&apos;s number when we pass a call to you
                        </label>
                        <Switch
                            aria-labelledby="show-caller-number"
                            checked={settings.show_caller_number}
                            disabled={disabled || switching || !can("agents:facts")}
                            onCheckedChange={(checked) => void setShowCaller(checked)}
                        />
                    </div>
                    <p className="text-[12.5px] leading-relaxed text-ink-3">{staffPhoneLine(settings)}</p>
                </div>
            )}
        </>
    );
}
