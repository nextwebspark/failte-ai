"use client";

import { BookOpen, Loader2, Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { archiveSkillApiV1SkillsSkillUuidDelete, importSkillApiV1SkillsImportPost } from "@/client/sdk.gen";
import type { SkillImportResponse, SkillSummaryResponse } from "@/client/types.gen";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Panel } from "@/components/ui/panel";
import { SectionHeading, SectionHint } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";

import { downloadSkillZip } from "./download";
import { NETWORK_ERROR, skillError } from "./errors";
import { type SkillAction, SkillCard } from "./SkillCard";
import { UpdateDialog } from "./UpdateDialog";
import { MAX_ACTIVE_SKILLS } from "./validation";

interface MySkillsTabProps {
    skills: SkillSummaryResponse[];
    loading: boolean;
    error: string | null;
    canWrite: boolean;
    onRetry: () => void;
    onChanged: () => Promise<void>;
    onBrowseLibrary: () => void;
}

export const LIMIT_MESSAGE = `This workspace has the maximum of ${MAX_ACTIVE_SKILLS} active skills. Archive one to add another.`;

export function MySkillsTab({ skills, loading, error, canWrite, onRetry, onChanged, onBrowseLibrary }: MySkillsTabProps) {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [importing, setImporting] = useState(false);
    const [imported, setImported] = useState<SkillImportResponse | null>(null);
    const [limitReached, setLimitReached] = useState(false);
    const [archiveTarget, setArchiveTarget] = useState<SkillSummaryResponse | null>(null);
    const [updateTarget, setUpdateTarget] = useState<SkillSummaryResponse | null>(null);
    const [busy, setBusy] = useState<{ id: string; action: SkillAction } | null>(null);

    const atLimit = limitReached || skills.length >= MAX_ACTIVE_SKILLS;

    const importFile = async (file: File) => {
        setImporting(true);
        try {
            const response = await importSkillApiV1SkillsImportPost({ body: { file } });
            if (response.error || !response.data) {
                const info = skillError(response.error, "Couldn't import the skill");
                if (info.kind === "limit") setLimitReached(true);
                toast.error(info.message);
                return;
            }
            await onChanged();
            if ((response.data.warnings ?? []).length > 0) {
                setImported(response.data);
            } else {
                toast.success(`Imported ${response.data.name}`);
            }
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setImporting(false);
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    };

    const archive = async (skill: SkillSummaryResponse) => {
        setBusy({ id: skill.skill_uuid, action: "archive" });
        try {
            const response = await archiveSkillApiV1SkillsSkillUuidDelete({ path: { skill_uuid: skill.skill_uuid } });
            if (response.error) {
                toast.error(skillError(response.error, "Couldn't archive the skill").message);
                return;
            }
            toast.success(`${skill.name} archived`);
            setLimitReached(false);
            await onChanged();
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setBusy(null);
        }
    };

    const runAction = async (skill: SkillSummaryResponse, action: SkillAction) => {
        if (action === "archive") {
            setArchiveTarget(skill);
            return;
        }
        if (action === "update") {
            setUpdateTarget(skill);
            return;
        }
        setBusy({ id: skill.skill_uuid, action });
        const problem = await downloadSkillZip(skill.skill_uuid, skill.name);
        setBusy(null);
        if (problem) toast.error(problem);
    };

    return (
        <div className="space-y-6">
            {canWrite ? (
                <div className="flex flex-wrap items-center gap-2">
                    {atLimit ? (
                        <Button disabled>
                            <Plus aria-hidden />
                            New skill
                        </Button>
                    ) : (
                        <Button asChild>
                            <Link href="/skills/new">
                                <Plus aria-hidden />
                                New skill
                            </Link>
                        </Button>
                    )}
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".zip,.md,application/zip,text/markdown"
                        className="hidden"
                        aria-hidden
                        tabIndex={-1}
                        data-testid="skill-import-input"
                        onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void importFile(file);
                        }}
                    />
                    <Button
                        variant="soft"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={importing || atLimit}
                    >
                        {importing ? <Loader2 className="animate-spin" aria-hidden /> : <Upload aria-hidden />}
                        Import
                    </Button>
                    <span className="text-xs text-muted-foreground">A skill folder as .zip, or a single SKILL.md</span>
                </div>
            ) : (
                <p className="text-sm text-muted-foreground">
                    You can view skills. Ask a workspace admin or developer to add or change them.
                </p>
            )}

            {canWrite && atLimit && (
                <Panel accent="amber" padding="sm" role="status">
                    <p className="text-sm">{LIMIT_MESSAGE}</p>
                </Panel>
            )}

            <section>
                <SectionHeading action={<SectionHint>{skills.length} active</SectionHint>}>Your skills</SectionHeading>
                {error ? (
                    <Panel accent="danger" padding="sm" className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-sm text-destructive">{error}</p>
                        <Button size="sm" variant="soft" onClick={onRetry}>
                            Try again
                        </Button>
                    </Panel>
                ) : loading ? (
                    <div className="space-y-3" aria-busy="true" aria-label="Loading skills">
                        {[0, 1, 2].map((i) => (
                            <Skeleton key={i} className="h-20 w-full" />
                        ))}
                    </div>
                ) : skills.length === 0 ? (
                    <Panel padding="default" className="flex flex-col items-start gap-3">
                        <div>
                            <p className="text-sm font-medium">No skills yet</p>
                            <p className="mt-1 text-sm text-ink-2">
                                Skills are playbooks your agents load only when a caller needs them, like a returns
                                policy or a booking procedure.
                            </p>
                        </div>
                        <Button size="sm" variant="soft" onClick={onBrowseLibrary}>
                            <BookOpen aria-hidden />
                            Browse the library
                        </Button>
                    </Panel>
                ) : (
                    <div className="grid gap-3">
                        {skills.map((skill) => (
                            <SkillCard
                                key={skill.skill_uuid}
                                skill={skill}
                                canWrite={canWrite}
                                busy={busy?.id === skill.skill_uuid ? busy.action : null}
                                onAction={(action) => void runAction(skill, action)}
                            />
                        ))}
                    </div>
                )}
            </section>

            <AlertDialog open={archiveTarget !== null} onOpenChange={(open) => !open && setArchiveTarget(null)}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Archive {archiveTarget?.name}?</AlertDialogTitle>
                        <AlertDialogDescription>
                            Agents stop seeing this skill on their next call. Steps that list or preload it skip it.
                            Its name becomes free for a new skill.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            className="bg-destructive text-white hover:bg-destructive/90"
                            onClick={() => {
                                if (archiveTarget) void archive(archiveTarget);
                                setArchiveTarget(null);
                            }}
                        >
                            Archive
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

            <UpdateDialog
                skill={updateTarget}
                canApply={canWrite}
                onOpenChange={(open) => !open && setUpdateTarget(null)}
                onApplied={() => void onChanged()}
            />

            <Dialog open={imported !== null} onOpenChange={(open) => !open && setImported(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Imported {imported?.name}</DialogTitle>
                        <DialogDescription>The skill was added, with these notes:</DialogDescription>
                    </DialogHeader>
                    <ul className="list-disc space-y-1 pl-5 text-sm" aria-label="Import notes">
                        {(imported?.warnings ?? []).map((warning) => (
                            <li key={warning}>{warning}</li>
                        ))}
                    </ul>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setImported(null)}>
                            Close
                        </Button>
                        {imported && (
                            <Button asChild>
                                <Link href={`/skills/${imported.skill_uuid}`}>Review skill</Link>
                            </Button>
                        )}
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
