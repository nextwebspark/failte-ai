"use client";

import { Check, Loader2, Pencil, Plus, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
    copyLibrarySkillApiV1SkillsFromLibraryLibrarySkillUuidPost,
    deprecateLibrarySkillApiV1SkillLibraryLibrarySkillUuidDeprecatePost,
    publishLibrarySkillApiV1SkillLibraryLibrarySkillUuidPublishPost,
    syncLibrarySeedsApiV1SkillLibrarySyncSeedsPost,
} from "@/client/sdk.gen";
import type { LibrarySkillSummaryResponse, SkillSummaryResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { SectionHeading, SectionHint } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, statusTone } from "@/components/ui/status-pill";

import { NETWORK_ERROR, skillError } from "./errors";
import { LibrarySkillDialog } from "./LibrarySkillDialog";
import { LIMIT_MESSAGE } from "./MySkillsTab";
import { MAX_ACTIVE_SKILLS, nameError } from "./validation";

interface LibraryTabProps {
    library: LibrarySkillSummaryResponse[];
    loading: boolean;
    error: string | null;
    workspaceSkills: SkillSummaryResponse[];
    canWrite: boolean;
    isPlatformAdmin: boolean;
    onRetry: () => void;
    onLibraryChanged: () => Promise<void>;
    onSkillAdded: () => Promise<void>;
}

interface ConflictState {
    skill: LibrarySkillSummaryResponse;
    name: string;
    message: string;
}

const ALL_CATEGORIES = "";

export function filterLibrary(
    skills: readonly LibrarySkillSummaryResponse[],
    query: string,
    category: string,
): LibrarySkillSummaryResponse[] {
    const needle = query.trim().toLowerCase();
    return skills.filter(
        (skill) =>
            (category === ALL_CATEGORIES || (skill.category ?? "") === category) &&
            (!needle ||
                skill.name.toLowerCase().includes(needle) ||
                skill.description.toLowerCase().includes(needle)),
    );
}

export function LibraryTab({
    library,
    loading,
    error,
    workspaceSkills,
    canWrite,
    isPlatformAdmin,
    onRetry,
    onLibraryChanged,
    onSkillAdded,
}: LibraryTabProps) {
    const [query, setQuery] = useState("");
    const [category, setCategory] = useState(ALL_CATEGORIES);
    const [viewing, setViewing] = useState<LibrarySkillSummaryResponse | null>(null);
    const [adding, setAdding] = useState<string | null>(null);
    const [conflict, setConflict] = useState<ConflictState | null>(null);
    const [adminBusy, setAdminBusy] = useState<string | null>(null);
    const [syncing, setSyncing] = useState(false);

    const categories = useMemo(
        () => [...new Set(library.map((s) => s.category).filter((c): c is string => Boolean(c)))].sort(),
        [library],
    );
    const visible = useMemo(() => filterLibrary(library, query, category), [library, query, category]);
    const copiedFrom = useMemo(
        () => new Set(workspaceSkills.map((s) => s.source_library_uuid).filter((u): u is string => Boolean(u))),
        [workspaceSkills],
    );
    const atLimit = workspaceSkills.length >= MAX_ACTIVE_SKILLS;

    const add = async (skill: LibrarySkillSummaryResponse, name?: string) => {
        setAdding(skill.library_skill_uuid);
        try {
            const response = await copyLibrarySkillApiV1SkillsFromLibraryLibrarySkillUuidPost({
                path: { library_skill_uuid: skill.library_skill_uuid },
                body: name ? { name } : {},
            });
            if (response.error || !response.data) {
                const info = skillError(response.error, "Couldn't add the skill");
                if (info.kind === "name_conflict") {
                    setViewing(null);
                    setConflict({ skill, name: info.suggestedName ?? name ?? skill.name, message: info.message });
                    return;
                }
                toast.error(info.kind === "limit" ? LIMIT_MESSAGE : info.message);
                return;
            }
            toast.success(`Added ${response.data.name} to your workspace`);
            setConflict(null);
            setViewing(null);
            await onSkillAdded();
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setAdding(null);
        }
    };

    const adminAction = async (skill: LibrarySkillSummaryResponse, action: "publish" | "deprecate") => {
        setAdminBusy(skill.library_skill_uuid);
        try {
            const call =
                action === "publish"
                    ? publishLibrarySkillApiV1SkillLibraryLibrarySkillUuidPublishPost
                    : deprecateLibrarySkillApiV1SkillLibraryLibrarySkillUuidDeprecatePost;
            const response = await call({ path: { library_skill_uuid: skill.library_skill_uuid } });
            if (response.error || !response.data) {
                toast.error(skillError(response.error, `Couldn't ${action} the skill`).message);
                return;
            }
            toast.success(
                action === "publish"
                    ? `Published ${skill.name} v${response.data.version}`
                    : `${skill.name} is hidden from the library`,
            );
            await onLibraryChanged();
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setAdminBusy(null);
        }
    };

    const syncSeeds = async () => {
        setSyncing(true);
        try {
            const response = await syncLibrarySeedsApiV1SkillLibrarySyncSeedsPost();
            if (response.error || !response.data) {
                toast.error(skillError(response.error, "Couldn't sync the seed skills").message);
                return;
            }
            const { created, updated, unchanged, skipped } = response.data;
            toast.success(
                `Seeds synced: ${created.length} new, ${updated.length} updated, ${unchanged.length} unchanged` +
                    (skipped.length ? `, ${skipped.length} skipped` : ""),
            );
            await onLibraryChanged();
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setSyncing(false);
        }
    };

    const conflictNameError = conflict ? nameError(conflict.name) : null;

    return (
        <div className="space-y-6">
            {isPlatformAdmin && (
                <Panel accent="sky" padding="sm" className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm text-ink-2">
                        Platform admin: you also see draft and deprecated skills. Edits to a published skill publish a
                        new version.
                    </p>
                    <div className="flex flex-wrap gap-2">
                        <Button size="sm" variant="soft" onClick={() => void syncSeeds()} disabled={syncing}>
                            {syncing ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                            Sync seeds
                        </Button>
                        <Button size="sm" asChild>
                            <Link href="/skills/library/new">
                                <Plus aria-hidden />
                                New library skill
                            </Link>
                        </Button>
                    </div>
                </Panel>
            )}

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                    <Search
                        className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-3"
                        aria-hidden
                    />
                    <Input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search skills"
                        aria-label="Search library skills"
                        className="pl-8"
                    />
                </div>
                {categories.length > 0 && (
                    <select
                        aria-label="Filter by category"
                        className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                        value={category}
                        onChange={(event) => setCategory(event.target.value)}
                    >
                        <option value={ALL_CATEGORIES}>All categories</option>
                        {categories.map((c) => (
                            <option key={c} value={c}>
                                {c}
                            </option>
                        ))}
                    </select>
                )}
            </div>

            <section>
                <SectionHeading action={<SectionHint>{visible.length} shown</SectionHint>}>Skill library</SectionHeading>
                {error ? (
                    <Panel accent="danger" padding="sm" className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-sm text-destructive">{error}</p>
                        <Button size="sm" variant="soft" onClick={onRetry}>
                            Try again
                        </Button>
                    </Panel>
                ) : loading ? (
                    <div className="grid gap-3 sm:grid-cols-2" aria-busy="true" aria-label="Loading library">
                        {[0, 1, 2, 3].map((i) => (
                            <Skeleton key={i} className="h-36 w-full" />
                        ))}
                    </div>
                ) : visible.length === 0 ? (
                    <Panel padding="sm">
                        <p className="text-sm text-ink-2">
                            {library.length === 0 ? "The library is empty for now." : "No skills match your search."}
                        </p>
                    </Panel>
                ) : (
                    <div className="grid items-start gap-3 sm:grid-cols-2">
                        {visible.map((skill) => {
                            const added = copiedFrom.has(skill.library_skill_uuid);
                            const canAdd = canWrite && skill.status === "published" && !atLimit;
                            return (
                                <Panel key={skill.library_skill_uuid} padding="sm" className="flex h-full flex-col gap-2">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="font-mono text-sm font-semibold">{skill.name}</span>
                                        <span className="font-mono text-[11px] text-ink-3">v{skill.version}</span>
                                        {skill.category && <StatusPill tone="mute">{skill.category}</StatusPill>}
                                        {isPlatformAdmin && skill.status !== "published" && (
                                            <StatusPill tone={statusTone(skill.status)}>{skill.status}</StatusPill>
                                        )}
                                        {added && (
                                            <StatusPill tone="ok">
                                                <Check className="mr-1 size-3" aria-hidden />
                                                In workspace
                                            </StatusPill>
                                        )}
                                    </div>
                                    <p className="line-clamp-3 flex-1 text-sm text-ink-2">{skill.description}</p>
                                    <div className="flex flex-wrap gap-1.5">
                                        <Button size="sm" variant="ghost" onClick={() => setViewing(skill)}>
                                            View
                                        </Button>
                                        {canAdd && (
                                            <Button
                                                size="sm"
                                                variant="soft"
                                                onClick={() => void add(skill)}
                                                disabled={adding === skill.library_skill_uuid}
                                                aria-label={`Add ${skill.name} to workspace`}
                                            >
                                                {adding === skill.library_skill_uuid ? (
                                                    <Loader2 className="animate-spin" aria-hidden />
                                                ) : (
                                                    <Plus aria-hidden />
                                                )}
                                                {added ? "Add another copy" : "Add to workspace"}
                                            </Button>
                                        )}
                                        {isPlatformAdmin && (
                                            <>
                                                <Button size="sm" variant="ghost" asChild>
                                                    <Link
                                                        href={`/skills/library/${skill.library_skill_uuid}`}
                                                        aria-label={`Edit library skill ${skill.name}`}
                                                    >
                                                        <Pencil aria-hidden />
                                                        Edit
                                                    </Link>
                                                </Button>
                                                {skill.status !== "published" && (
                                                    <Button
                                                        size="sm"
                                                        variant="ghost"
                                                        disabled={adminBusy === skill.library_skill_uuid}
                                                        onClick={() => void adminAction(skill, "publish")}
                                                    >
                                                        Publish
                                                    </Button>
                                                )}
                                                {skill.status === "published" && (
                                                    <Button
                                                        size="sm"
                                                        variant="ghost"
                                                        disabled={adminBusy === skill.library_skill_uuid}
                                                        onClick={() => void adminAction(skill, "deprecate")}
                                                    >
                                                        Deprecate
                                                    </Button>
                                                )}
                                            </>
                                        )}
                                    </div>
                                </Panel>
                            );
                        })}
                    </div>
                )}
                {canWrite && atLimit && <p className="mt-3 text-sm text-ink-2">{LIMIT_MESSAGE}</p>}
            </section>

            <LibrarySkillDialog
                skill={viewing}
                canAdd={Boolean(viewing && canWrite && viewing.status === "published" && !atLimit)}
                onOpenChange={(open) => !open && setViewing(null)}
                onAdd={(skill) => void add(skill)}
            />

            <Dialog open={conflict !== null} onOpenChange={(open) => !open && setConflict(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Choose another name</DialogTitle>
                        <DialogDescription>
                            Your workspace already has a skill named {conflict?.skill.name}. Add this copy under a
                            different name.
                        </DialogDescription>
                    </DialogHeader>
                    <form
                        className="space-y-2"
                        onSubmit={(event) => {
                            event.preventDefault();
                            if (conflict && !conflictNameError) void add(conflict.skill, conflict.name);
                        }}
                    >
                        <Label htmlFor="copy-name">Name</Label>
                        <Input
                            id="copy-name"
                            value={conflict?.name ?? ""}
                            onChange={(event) =>
                                setConflict((current) => (current ? { ...current, name: event.target.value } : current))
                            }
                            className="font-mono"
                            aria-invalid={Boolean(conflictNameError)}
                            aria-describedby="copy-name-error"
                        />
                        {conflictNameError && (
                            <p id="copy-name-error" className="text-xs text-destructive">
                                {conflictNameError}
                            </p>
                        )}
                        <DialogFooter className="pt-2">
                            <Button type="button" variant="outline" onClick={() => setConflict(null)}>
                                Cancel
                            </Button>
                            <Button type="submit" disabled={Boolean(conflictNameError) || adding !== null}>
                                {adding !== null && <Loader2 className="animate-spin" aria-hidden />}
                                Add as {conflict?.name}
                            </Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </div>
    );
}
