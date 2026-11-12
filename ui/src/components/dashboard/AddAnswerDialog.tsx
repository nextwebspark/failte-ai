"use client";

import { useEffect, useId, useState } from "react";
import { toast } from "sonner";

import {
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet,
    markFollowUpDoneApiV1FollowUpsRunIdDonePost,
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut,
} from "@/client/sdk.gen";
import type { FollowUpItem } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

import { appendAnswer } from "./dashboardView";
import { notifyFollowUpsChanged } from "./useDashboardData";

/** Where the agent keeps its answers to common questions (a business fact). */
export const ANSWERS_FACT = "extra_info";

const SAVE_FAILED = "Couldn't save the answer. Please try again.";

/**
 * Add an answer to a question the agent couldn't answer: the question, a box
 * for the answer, and Save, which adds "Q: … A: …" to the agent's answers to
 * common questions and marks the follow-up done.
 */
export function AddAnswerDialog({
    item,
    onClose,
    onSaved,
}: {
    /** The follow-up being answered (a call, its agent and the questions);
     * null closes the dialog. */
    item: Pick<FollowUpItem, "run_id" | "workflow_id" | "questions"> | null;
    onClose: () => void;
    /** After saving: the agent's answers as now stored, and what was added. */
    onSaved?: (answers: string, added: { question: string; answer: string }) => void;
}) {
    const [answer, setAnswer] = useState("");
    const [saving, setSaving] = useState(false);
    const id = useId();
    const question = item?.questions.join(" ") ?? "";

    useEffect(() => {
        if (item) setAnswer("");
    }, [item]);

    const save = async () => {
        if (!item || !answer.trim() || saving) return;
        setSaving(true);
        try {
            const path = { workflow_id: item.workflow_id };
            const current = await getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet({ path });
            const fact = current.data?.facts.find((f) => f.key === ANSWERS_FACT);
            if (current.error || !fact) {
                toast.error(
                    current.error
                        ? SAVE_FAILED
                        : "This agent has no list of answers to add to. Change its wording in advanced setup.",
                );
                return;
            }
            const answers = appendAnswer(fact.value, question, answer);
            if (answers.length > fact.max_length) {
                toast.error("Your agent's answers are full. Shorten some on What your agent knows, then try again.");
                return;
            }
            const saved = await updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut({
                path,
                body: { facts: { [ANSWERS_FACT]: answers } },
            });
            if (saved.error || !saved.data) {
                toast.error(detailFromError(saved.error, SAVE_FAILED));
                return;
            }
            // The answer is saved; a failed mark only leaves the item on the list.
            await markFollowUpDoneApiV1FollowUpsRunIdDonePost({
                path: { run_id: item.run_id },
                query: { kind: "unanswered_question" },
            }).catch(() => undefined);
            notifyFollowUpsChanged();
            toast.success("Answer added. Your agent uses it from its next call.");
            onSaved?.(saved.data.facts.find((f) => f.key === ANSWERS_FACT)?.value ?? answers, { question, answer });
            onClose();
        } catch {
            toast.error(SAVE_FAILED);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={item !== null} onOpenChange={(open) => !open && !saving && onClose()}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>Add an answer</DialogTitle>
                    <DialogDescription>Your agent uses it the next time someone asks.</DialogDescription>
                </DialogHeader>
                <form
                    className="flex flex-col gap-3"
                    onSubmit={(event) => {
                        event.preventDefault();
                        void save();
                    }}
                >
                    <div>
                        <p className="text-caption font-medium text-ink-3">The caller asked</p>
                        <p className="mt-1 rounded-lg bg-panel-2 px-3 py-2 text-sm font-semibold text-foreground">
                            {question}
                        </p>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor={`${id}-answer`} className="text-caption">
                            Your answer
                        </Label>
                        <Textarea
                            id={`${id}-answer`}
                            value={answer}
                            onChange={(e) => setAnswer(e.target.value)}
                            rows={3}
                            maxLength={500}
                            placeholder="e.g. Yes, we have gluten-free pasta. Just ask when you order."
                            className="text-sm"
                            autoFocus
                        />
                    </div>
                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
                            Cancel
                        </Button>
                        <Button type="submit" disabled={saving || !answer.trim()}>
                            {saving ? "Saving…" : "Save answer"}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}
