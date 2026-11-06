"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet,
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut,
} from "@/client/sdk.gen";
import type { BusinessFact } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";

/**
 * What the agent tells callers about the business. The owner edits these
 * here; the agent uses them from its next call, with no agent editor.
 */
export default function BusinessFactsPage() {
    const params = useParams<{ workflowId: string }>();
    const workflowId = Number(params.workflowId);
    const { can } = useOrgConfig();
    const canEdit = can("agents:facts");

    const [facts, setFacts] = useState<BusinessFact[] | null>(null);
    const [values, setValues] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const load = useCallback(async () => {
        setError(null);
        const res = await getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet({
            path: { workflow_id: workflowId },
        });
        if (res.error || !res.data) {
            setError(detailFromError(res.error, "Couldn't load the business facts."));
            return;
        }
        setFacts(res.data.facts);
        setValues(Object.fromEntries(res.data.facts.map((f) => [f.key, f.value])));
    }, [workflowId]);

    useEffect(() => {
        void load();
    }, [load]);

    const changed = (facts ?? []).filter((f) => (values[f.key] ?? "") !== f.value);

    const save = async () => {
        setSaving(true);
        const res = await updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut({
            path: { workflow_id: workflowId },
            body: { facts: Object.fromEntries(changed.map((f) => [f.key, values[f.key] ?? ""])) },
        });
        setSaving(false);
        if (res.error || !res.data) {
            toast.error(detailFromError(res.error, "Couldn't save. Please try again."));
            return;
        }
        setFacts(res.data.facts);
        setValues(Object.fromEntries(res.data.facts.map((f) => [f.key, f.value])));
        toast.success("Saved. Your agent uses these from its next call.");
    };

    if (error) {
        return (
            <div className="page-body">
                <Panel accent="danger" role="alert">
                    <PanelTitle>{error}</PanelTitle>
                    <Button className="mt-3" size="sm" variant="outline" onClick={() => void load()}>
                        Try again
                    </Button>
                </Panel>
            </div>
        );
    }
    if (!facts) {
        return (
            <div className="page-body flex flex-col gap-3" aria-busy="true">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
            </div>
        );
    }
    if (facts.length === 0) {
        return (
            <div className="page-body">
                <Panel>
                    <PanelTitle>This agent has no business facts to edit here.</PanelTitle>
                    <p className="mt-2 text-sm text-ink-2">
                        Agents made from a ready-made template keep their opening hours, address and answers here.
                        This one was built differently, so its wording lives in the conversation itself.
                    </p>
                </Panel>
            </div>
        );
    }

    return (
        <div className="page-body flex max-w-2xl flex-col gap-5">
            <p className="text-sm text-ink-2">
                What your agent tells callers about your business. Changes apply from the next call.
            </p>
            {facts.map((fact) => {
                const id = `fact-${fact.key}`;
                const common = {
                    id,
                    value: values[fact.key] ?? "",
                    maxLength: fact.max_length,
                    disabled: !canEdit || saving,
                    placeholder: fact.placeholder ? `e.g. ${fact.placeholder}` : undefined,
                };
                return (
                    <div key={fact.key} className="flex flex-col gap-1.5">
                        <Label htmlFor={id}>
                            {fact.label}
                            {!fact.required && <span className="font-normal text-ink-3"> Optional</span>}
                        </Label>
                        {fact.type === "textarea" ? (
                            <Textarea
                                {...common}
                                rows={3}
                                onChange={(e) => setValues((v) => ({ ...v, [fact.key]: e.target.value }))}
                            />
                        ) : (
                            <Input
                                {...common}
                                onChange={(e) => setValues((v) => ({ ...v, [fact.key]: e.target.value }))}
                            />
                        )}
                        {fact.help && <p className="text-[12.5px] text-ink-3">{fact.help}</p>}
                    </div>
                );
            })}
            {canEdit ? (
                <div className="flex gap-2">
                    <Button onClick={() => void save()} disabled={saving || changed.length === 0}>
                        {saving ? "Saving…" : "Save changes"}
                    </Button>
                    {changed.length > 0 && (
                        <Button
                            variant="outline"
                            disabled={saving}
                            onClick={() => setValues(Object.fromEntries(facts.map((f) => [f.key, f.value])))}
                        >
                            Undo
                        </Button>
                    )}
                </div>
            ) : (
                <p className="text-sm text-ink-3">Only the owner or an admin can change these.</p>
            )}
        </div>
    );
}
