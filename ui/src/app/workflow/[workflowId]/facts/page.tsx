"use client";

import { BookOpenText } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet,
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut,
} from "@/client/sdk.gen";
import type { BusinessFact } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SectionHeading } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useAgentShell } from "@/context/AgentShellContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";

import { AgentHomeSummary } from "../components/AgentHomeSummary";
import { SectionError, SectionMessage } from "../components/SectionStates";

const LOAD_FAILED = "We couldn't load your business facts";
const SAVE_FAILED = "Couldn't save. Please try again.";

/**
 * Opening an agent lands here: the agent's summary on top, then what it tells
 * callers about the business. The owner edits these here; the agent uses them
 * from its next call, with no agent editor.
 */
export default function BusinessFactsPage() {
    const params = useParams<{ workflowId: string }>();
    const workflowId = Number(params.workflowId);
    useOpenTesterFromOnboarding();

    return (
        <div className="page-body flex max-w-3xl flex-col gap-8">
            <AgentHomeSummary workflowId={workflowId} />
            <section aria-labelledby="facts-title">
                <SectionHeading id="facts-title">Business facts</SectionHeading>
                <BusinessFacts workflowId={workflowId} />
            </section>
        </div>
    );
}

/**
 * Straight after creating an agent the wizard sends the owner here with
 * ?onboarding=web_call: open the test panel once, then drop the flag so a
 * refresh or Back doesn't open it again.
 */
function useOpenTesterFromOnboarding() {
    const searchParams = useSearchParams();
    const router = useRouter();
    const pathname = usePathname();
    const { openTester } = useAgentShell();
    const opened = useRef(false);

    useEffect(() => {
        if (opened.current || searchParams.get("onboarding") !== "web_call") return;
        opened.current = true;
        openTester();
        const next = new URLSearchParams(searchParams.toString());
        next.delete("onboarding");
        const query = next.toString();
        router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    }, [openTester, pathname, router, searchParams]);
}

function BusinessFacts({ workflowId }: { workflowId: number }) {
    const { can } = useOrgConfig();
    const canEdit = can("agents:facts");

    const [facts, setFacts] = useState<BusinessFact[] | null>(null);
    const [values, setValues] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    // Set synchronously so a double click can't send two saves.
    const savingRef = useRef(false);
    // Required-field messages show once the owner has tried to save.
    const [triedSave, setTriedSave] = useState(false);

    const load = useCallback(async () => {
        setError(null);
        setFacts(null);
        try {
            const res = await getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet({
                path: { workflow_id: workflowId },
            });
            if (res.error || !res.data) {
                setError(LOAD_FAILED);
                return;
            }
            setFacts(res.data.facts);
            setValues(Object.fromEntries(res.data.facts.map((f) => [f.key, f.value])));
        } catch {
            setError(LOAD_FAILED);
        }
    }, [workflowId]);

    useEffect(() => {
        void load();
    }, [load]);

    const changed = (facts ?? []).filter((f) => (values[f.key] ?? "") !== f.value);
    const missing = new Set(
        (facts ?? []).filter((f) => f.required && !(values[f.key] ?? "").trim()).map((f) => f.key),
    );

    const save = async () => {
        if (savingRef.current || changed.length === 0) return;
        setTriedSave(true);
        if (missing.size > 0) {
            toast.error("Fill in the required answers before saving.");
            return;
        }
        savingRef.current = true;
        setSaving(true);
        try {
            const res = await updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut({
                path: { workflow_id: workflowId },
                body: { facts: Object.fromEntries(changed.map((f) => [f.key, values[f.key] ?? ""])) },
            });
            if (res.error || !res.data) {
                toast.error(detailFromError(res.error, SAVE_FAILED));
                return;
            }
            setFacts(res.data.facts);
            setValues(Object.fromEntries(res.data.facts.map((f) => [f.key, f.value])));
            setTriedSave(false);
            toast.success("Saved. Your agent uses these from its next call.");
        } catch {
            toast.error(SAVE_FAILED);
        } finally {
            savingRef.current = false;
            setSaving(false);
        }
    };

    if (error) {
        return <SectionError title={error} onRetry={() => void load()} />;
    }
    if (!facts) {
        return (
            <div className="flex flex-col gap-5" aria-busy="true" aria-label="Loading business facts">
                {[0, 1, 2].map((i) => (
                    <div key={i} className="flex flex-col gap-1.5">
                        <Skeleton className="h-4 w-36" />
                        <Skeleton className="h-10 w-full" />
                    </div>
                ))}
            </div>
        );
    }
    if (facts.length === 0) {
        return (
            <SectionMessage icon={<BookOpenText />} title="This agent has no business facts to edit here.">
                Agents made from a ready-made template keep their opening hours, address and answers here.
                This one was built differently, so its wording lives in the{" "}
                <Link
                    href={`/workflow/${workflowId}`}
                    className="font-medium text-brand underline-offset-2 hover:underline"
                >
                    conversation
                </Link>{" "}
                itself.
            </SectionMessage>
        );
    }

    return (
        <div className="flex flex-col gap-5">
            <p className="text-sm text-ink-2">
                What your agent tells callers about your business. Changes apply from the next call.
            </p>
            {facts.map((fact) => {
                const id = `fact-${fact.key}`;
                const errorId = `${id}-error`;
                const invalid = triedSave && missing.has(fact.key);
                const common = {
                    id,
                    value: values[fact.key] ?? "",
                    maxLength: fact.max_length,
                    disabled: !canEdit || saving,
                    required: fact.required,
                    "aria-invalid": invalid || undefined,
                    "aria-describedby": invalid ? errorId : undefined,
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
                                className="h-10"
                                onChange={(e) => setValues((v) => ({ ...v, [fact.key]: e.target.value }))}
                            />
                        )}
                        {invalid && (
                            <p id={errorId} className="text-[12.5px] text-danger">
                                Your agent needs this answer. Please fill it in.
                            </p>
                        )}
                        {fact.help && <p className="text-[12.5px] text-ink-3">{fact.help}</p>}
                    </div>
                );
            })}
            {canEdit ? (
                <div className="flex flex-wrap items-center gap-2">
                    <Button size="lg" onClick={() => void save()} disabled={saving || changed.length === 0}>
                        {saving ? "Saving…" : "Save changes"}
                    </Button>
                    {changed.length > 0 && (
                        <Button
                            size="lg"
                            variant="outline"
                            disabled={saving}
                            onClick={() => setValues(Object.fromEntries(facts.map((f) => [f.key, f.value])))}
                        >
                            Undo
                        </Button>
                    )}
                    {changed.length > 0 && !saving && (
                        <span className="text-[12.5px] text-ink-3">
                            {changed.length === 1 ? "1 unsaved change" : `${changed.length} unsaved changes`}
                        </span>
                    )}
                </div>
            ) : (
                <p className="text-sm text-ink-3">Only the owner or an admin can change these.</p>
            )}
        </div>
    );
}
