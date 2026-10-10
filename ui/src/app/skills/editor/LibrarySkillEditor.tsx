"use client";

import { ArrowLeft, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    createLibrarySkillApiV1SkillLibraryPost,
    deprecateLibrarySkillApiV1SkillLibraryLibrarySkillUuidDeprecatePost,
    getLibrarySkillApiV1SkillLibraryLibrarySkillUuidGet,
    publishLibrarySkillApiV1SkillLibraryLibrarySkillUuidPublishPost,
    updateLibrarySkillApiV1SkillLibraryLibrarySkillUuidPatch,
} from "@/client/sdk.gen";
import type { LibrarySkillResponse } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, statusTone } from "@/components/ui/status-pill";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";

import { NETWORK_ERROR, skillError } from "../errors";
import { usePlatformAdmin } from "../useSkills";
import { categoryError, hasErrors } from "../validation";
import {
    draftErrors,
    draftFromSkill,
    type EditorDraft,
    emptyDraft,
    isDirty,
    libraryUpdateBody,
} from "./editorModel";
import { type NameConflict, SkillEditorForm } from "./SkillEditorForm";
import { useLeaveGuard } from "./useLeaveGuard";

/** Platform-admin editor for a library skill (`libraryUuid` null creates a draft). */
export function LibrarySkillEditor({ libraryUuid }: { libraryUuid: string | null }) {
    const isPlatformAdmin = usePlatformAdmin();
    const { role } = useOrgConfig();
    if (isPlatformAdmin === null) return null;
    if (!isPlatformAdmin) return <NoAccess role={role} />;
    return <LibraryEditorScreen libraryUuid={libraryUuid} />;
}

function LibraryEditorScreen({ libraryUuid }: { libraryUuid: string | null }) {
    const router = useRouter();
    const { user, loading: authLoading } = useAuth();
    const [skill, setSkill] = useState<LibrarySkillResponse | null>(null);
    const [baseline, setBaseline] = useState<EditorDraft>(emptyDraft);
    const [draft, setDraft] = useState<EditorDraft>(emptyDraft);
    const [loading, setLoading] = useState(libraryUuid !== null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [busy, setBusy] = useState<"save" | "publish" | "deprecate" | null>(null);
    const [showErrors, setShowErrors] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const [nameConflict, setNameConflict] = useState<NameConflict | null>(null);
    const hasFetched = useRef(false);

    const errors = useMemo(() => draftErrors(draft), [draft]);
    const dirty = isDirty(draft, baseline);
    useLeaveGuard("library-skill-editor", dirty);

    const applySkill = useCallback((next: LibrarySkillResponse) => {
        const nextDraft = draftFromSkill(next);
        setSkill(next);
        setBaseline(nextDraft);
        setDraft(nextDraft);
    }, []);

    useEffect(() => {
        if (!libraryUuid || authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void (async () => {
            try {
                const response = await getLibrarySkillApiV1SkillLibraryLibrarySkillUuidGet({
                    path: { library_skill_uuid: libraryUuid },
                });
                if (response.error || !response.data) {
                    setLoadError(skillError(response.error, "Couldn't load this library skill").message);
                    return;
                }
                applySkill(response.data);
            } catch {
                setLoadError(NETWORK_ERROR);
            } finally {
                setLoading(false);
            }
        })();
    }, [authLoading, user, libraryUuid, applySkill]);

    const save = async () => {
        setShowErrors(true);
        setFormError(null);
        if (hasErrors(errors) || categoryError(draft.category)) {
            setFormError("Fix the highlighted fields, then save again.");
            return;
        }
        setBusy("save");
        try {
            const response = libraryUuid
                ? await updateLibrarySkillApiV1SkillLibraryLibrarySkillUuidPatch({
                      path: { library_skill_uuid: libraryUuid },
                      body: libraryUpdateBody(draft, baseline),
                  })
                : await createLibrarySkillApiV1SkillLibraryPost({
                      body: {
                          name: draft.name,
                          description: draft.description.trim(),
                          body_md: draft.body_md,
                          files: draft.files.map((f) => ({ path: f.path.trim(), content: f.content })),
                          category: draft.category.trim() || null,
                      },
                  });
            if (response.error || !response.data) {
                const info = skillError(response.error, "Couldn't save the library skill");
                if (info.kind === "name_conflict") {
                    setNameConflict({ message: info.message, suggestedName: info.suggestedName });
                } else {
                    setFormError(info.message);
                }
                return;
            }
            setNameConflict(null);
            setShowErrors(false);
            applySkill(response.data);
            toast.success(libraryUuid ? `Saved ${response.data.name} (v${response.data.version})` : "Draft created");
            if (!libraryUuid) router.replace(`/skills/library/${response.data.library_skill_uuid}`);
        } catch {
            setFormError(NETWORK_ERROR);
        } finally {
            setBusy(null);
        }
    };

    const lifecycle = async (action: "publish" | "deprecate") => {
        if (!libraryUuid) return;
        setBusy(action);
        try {
            const call =
                action === "publish"
                    ? publishLibrarySkillApiV1SkillLibraryLibrarySkillUuidPublishPost
                    : deprecateLibrarySkillApiV1SkillLibraryLibrarySkillUuidDeprecatePost;
            const response = await call({ path: { library_skill_uuid: libraryUuid } });
            if (response.error || !response.data) {
                toast.error(skillError(response.error, `Couldn't ${action} the skill`).message);
                return;
            }
            applySkill(response.data);
            toast.success(action === "publish" ? `Published v${response.data.version}` : "Deprecated");
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="page-body">
            <div className="w-full max-w-4xl space-y-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                        <Link
                            href="/skills?tab=library"
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                        >
                            <ArrowLeft className="size-3.5" aria-hidden />
                            Skill library
                        </Link>
                        <div className="flex flex-wrap items-center gap-2">
                            <h1 className="truncate font-mono text-lg font-semibold">
                                {libraryUuid ? (skill?.name ?? "Library skill") : "New library skill"}
                            </h1>
                            {skill && <span className="font-mono text-xs text-ink-3">v{skill.version}</span>}
                            {skill && <StatusPill tone={statusTone(skill.status)}>{skill.status}</StatusPill>}
                            {skill?.is_seeded && <StatusPill tone="mute">Seed</StatusPill>}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {skill && skill.status !== "published" && (
                            <Button variant="soft" disabled={busy !== null || dirty} onClick={() => void lifecycle("publish")}>
                                Publish
                            </Button>
                        )}
                        {skill?.status === "published" && (
                            <Button variant="soft" disabled={busy !== null} onClick={() => void lifecycle("deprecate")}>
                                Deprecate
                            </Button>
                        )}
                        <Button onClick={() => void save()} disabled={busy !== null || (libraryUuid !== null && !dirty)}>
                            {busy === "save" ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
                            {libraryUuid ? "Save" : "Create draft"}
                        </Button>
                    </div>
                </div>

                <p className="text-xs text-muted-foreground">
                    {skill?.status === "published"
                        ? "Saving changes publishes a new version. Workspaces that copied this skill see “Update available”."
                        : "Drafts are visible only to platform admins until published."}
                    {skill?.is_seeded && " Edits to a seed skill last until its seed folder changes in the code."}
                </p>

                {formError && (
                    <Panel accent="danger" padding="sm" role="alert">
                        <p className="text-sm text-destructive">{formError}</p>
                    </Panel>
                )}

                {loadError ? (
                    <Panel accent="danger" padding="sm" role="alert">
                        <p className="text-sm text-destructive">{loadError}</p>
                    </Panel>
                ) : loading ? (
                    <div className="space-y-4" aria-busy="true" aria-label="Loading skill">
                        <Skeleton className="h-40 w-full" />
                        <Skeleton className="h-80 w-full" />
                    </div>
                ) : (
                    <SkillEditorForm
                        mode="library"
                        draft={draft}
                        onChange={(next) => {
                            setDraft(next);
                            if (nameConflict && next.name !== draft.name) setNameConflict(null);
                        }}
                        errors={errors}
                        showErrors={showErrors}
                        readOnly={false}
                        tools={[]}
                        nameConflict={nameConflict}
                    />
                )}
            </div>
        </div>
    );
}
