"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
    applyLibraryUpdateApiV1SkillsSkillUuidApplyLibraryUpdatePost,
    getLibraryDiffApiV1SkillsSkillUuidLibraryDiffGet,
} from "@/client/sdk.gen";
import type { LibraryDiffResponse, SkillResponse, SkillSummaryResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";

import { DiffView } from "./DiffView";
import { NETWORK_ERROR, skillError } from "./errors";

interface UpdateDialogProps {
    skill: SkillSummaryResponse | null;
    canApply: boolean;
    onOpenChange: (open: boolean) => void;
    onApplied: (skill: SkillResponse) => void;
}

/**
 * Shows what changed in the library since this copy was taken and applies it.
 * A copy edited in the workspace is only replaced after an explicit
 * confirmation (`force`).
 */
export function UpdateDialog({ skill, canApply, onOpenChange, onApplied }: UpdateDialogProps) {
    const [diff, setDiff] = useState<LibraryDiffResponse | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [modified, setModified] = useState(false);
    const [confirmed, setConfirmed] = useState(false);
    const [applying, setApplying] = useState(false);

    const skillUuid = skill?.skill_uuid ?? null;
    useEffect(() => {
        setDiff(null);
        setLoadError(null);
        setConfirmed(false);
        setModified(skill?.is_modified ?? false);
        if (!skillUuid) return;
        let cancelled = false;
        void (async () => {
            try {
                const response = await getLibraryDiffApiV1SkillsSkillUuidLibraryDiffGet({
                    path: { skill_uuid: skillUuid },
                });
                if (cancelled) return;
                if (response.error || !response.data) {
                    setLoadError(skillError(response.error, "Couldn't load the library changes").message);
                    return;
                }
                setDiff(response.data);
                setModified(response.data.is_modified);
            } catch {
                if (!cancelled) setLoadError(NETWORK_ERROR);
            }
        })();
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [skillUuid]);

    const apply = async () => {
        if (!skillUuid) return;
        setApplying(true);
        try {
            const response = await applyLibraryUpdateApiV1SkillsSkillUuidApplyLibraryUpdatePost({
                path: { skill_uuid: skillUuid },
                body: { strategy: "replace", force: modified && confirmed },
            });
            if (response.error || !response.data) {
                const info = skillError(response.error, "Couldn't apply the update");
                if (info.kind === "modified") {
                    // Edited since the dialog opened: ask for confirmation first.
                    setModified(true);
                    setConfirmed(false);
                }
                toast.error(info.message);
                return;
            }
            toast.success(`${response.data.name} is up to date with the library`);
            onApplied(response.data);
            onOpenChange(false);
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setApplying(false);
        }
    };

    const versionLabel = diff
        ? `Your copy is from version ${diff.source_version ?? "?"}; the library is at version ${diff.latest_version}.`
        : "Loading the latest library version…";

    return (
        <Dialog open={skill !== null} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>Update {skill?.name}</DialogTitle>
                    <DialogDescription>{versionLabel}</DialogDescription>
                </DialogHeader>

                {loadError ? (
                    <p className="text-sm text-destructive" role="alert">
                        {loadError}
                    </p>
                ) : diff ? (
                    <div className="space-y-3">
                        {diff.library_status === "deprecated" && (
                            <p className="text-sm text-ink-2">This library skill has been retired.</p>
                        )}
                        <DiffView diff={diff.diff} />
                        <p className="text-xs text-muted-foreground">
                            Lines starting with − are in your copy, lines with + are in the library version.
                        </p>
                    </div>
                ) : (
                    <Skeleton className="h-48 w-full" aria-label="Loading changes" />
                )}

                {canApply && modified && (
                    <Panel accent="amber" padding="sm" className="space-y-2">
                        <p className="text-sm font-medium">This copy was edited in your workspace</p>
                        <p className="text-sm text-ink-2">
                            Applying the update replaces your edits with the library version. Export the skill first
                            if you want to keep a copy.
                        </p>
                        <div className="flex items-center gap-2">
                            <Checkbox
                                id="confirm-replace"
                                checked={confirmed}
                                onCheckedChange={(checked) => setConfirmed(checked === true)}
                            />
                            <Label htmlFor="confirm-replace" className="text-sm">
                                Replace my edits
                            </Label>
                        </div>
                    </Panel>
                )}

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {canApply ? "Cancel" : "Close"}
                    </Button>
                    {canApply && (
                        <Button
                            onClick={() => void apply()}
                            disabled={!diff || applying || (modified && !confirmed)}
                        >
                            {applying && <Loader2 className="animate-spin" aria-hidden />}
                            {modified ? "Replace with library version" : "Apply update"}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
