"use client";

import { FileText, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { getLibrarySkillApiV1SkillLibraryLibrarySkillUuidGet } from "@/client/sdk.gen";
import type { LibrarySkillResponse, LibrarySkillSummaryResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

import { NETWORK_ERROR, skillError } from "./errors";
import { MarkdownPreview } from "./MarkdownPreview";
import { byteLength, formatBytes } from "./validation";

interface LibrarySkillDialogProps {
    skill: LibrarySkillSummaryResponse | null;
    canAdd: boolean;
    onOpenChange: (open: boolean) => void;
    onAdd: (skill: LibrarySkillSummaryResponse) => void;
}

export function LibrarySkillDialog({ skill, canAdd, onOpenChange, onAdd }: LibrarySkillDialogProps) {
    const [detail, setDetail] = useState<LibrarySkillResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const uuid = skill?.library_skill_uuid ?? null;

    useEffect(() => {
        setDetail(null);
        setError(null);
        if (!uuid) return;
        let cancelled = false;
        void (async () => {
            try {
                const response = await getLibrarySkillApiV1SkillLibraryLibrarySkillUuidGet({
                    path: { library_skill_uuid: uuid },
                });
                if (cancelled) return;
                if (response.error || !response.data) {
                    setError(skillError(response.error, "Couldn't load this skill").message);
                    return;
                }
                setDetail(response.data);
            } catch {
                if (!cancelled) setError(NETWORK_ERROR);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [uuid]);

    return (
        <Dialog open={skill !== null} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="font-mono">{skill?.name}</DialogTitle>
                    <DialogDescription>{skill?.description}</DialogDescription>
                </DialogHeader>
                {error ? (
                    <p className="text-sm text-destructive" role="alert">
                        {error}
                    </p>
                ) : detail ? (
                    <div className="space-y-4">
                        <div className="rounded-md border border-line bg-panel-2 p-4">
                            <MarkdownPreview source={detail.body_md} />
                        </div>
                        {detail.files.length > 0 && (
                            <div>
                                <h3 className="mb-2 text-sm font-semibold">Files</h3>
                                <ul className="space-y-1">
                                    {detail.files.map((file) => (
                                        <li key={file.path} className="flex items-center gap-2 text-sm">
                                            <FileText className="size-3.5 text-ink-3" aria-hidden />
                                            <span className="font-mono text-xs">{file.path}</span>
                                            <span className="text-xs text-muted-foreground">
                                                {formatBytes(byteLength(file.content))}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                ) : (
                    <Skeleton className="h-48 w-full" aria-label="Loading skill" />
                )}
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Close
                    </Button>
                    {canAdd && skill && (
                        <Button onClick={() => onAdd(skill)}>
                            <Plus aria-hidden />
                            Add to workspace
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
