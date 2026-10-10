"use client";

import { ArrowLeft, Download, Loader2, RefreshCw, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    createSkillApiV1SkillsPost,
    getSkillApiV1SkillsSkillUuidGet,
    listToolsApiV1ToolsGet,
    updateSkillApiV1SkillsSkillUuidPatch,
} from "@/client/sdk.gen";
import type { SkillResponse, ToolResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import { useCanEditSkills } from "../access";
import { downloadSkillZip } from "../download";
import { NETWORK_ERROR, skillError } from "../errors";
import { LIMIT_MESSAGE } from "../MySkillsTab";
import { sourceLabel } from "../SkillCard";
import { UpdateDialog } from "../UpdateDialog";
import { hasErrors } from "../validation";
import {
    createBody,
    draftErrors,
    draftFromSkill,
    type EditorDraft,
    emptyDraft,
    isDirty,
    updateBody,
} from "./editorModel";
import { type NameConflict, SkillEditorForm } from "./SkillEditorForm";
import { useLeaveGuard } from "./useLeaveGuard";

/** Create (`skillUuid` null) or edit a workspace skill. */
export function WorkspaceSkillEditor({ skillUuid }: { skillUuid: string | null }) {
    const router = useRouter();
    const { user, loading: authLoading } = useAuth();
    const canWrite = useCanEditSkills();
    const readOnly = !canWrite;

    const [skill, setSkill] = useState<SkillResponse | null>(null);
    const [baseline, setBaseline] = useState<EditorDraft>(emptyDraft);
    const [draft, setDraft] = useState<EditorDraft>(emptyDraft);
    const [tools, setTools] = useState<ToolResponse[]>([]);
    const [toolsError, setToolsError] = useState<string | null>(null);
    const [loading, setLoading] = useState(skillUuid !== null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [showErrors, setShowErrors] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const [nameConflict, setNameConflict] = useState<NameConflict | null>(null);
    const [updateOpen, setUpdateOpen] = useState(false);
    const [exporting, setExporting] = useState(false);
    const hasFetched = useRef(false);

    const errors = useMemo(() => draftErrors(draft), [draft]);
    const dirty = isDirty(draft, baseline);
    useLeaveGuard("skill-editor", dirty && !readOnly);

    // The latest files, so re-baselining after a save keeps their ids.
    const filesRef = useRef(draft.files);
    filesRef.current = draft.files;

    const applySkill = useCallback((next: SkillResponse) => {
        const nextDraft = draftFromSkill(next, filesRef.current);
        setSkill(next);
        setBaseline(nextDraft);
        setDraft(nextDraft);
    }, []);

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void (async () => {
            try {
                const toolsResponse = await listToolsApiV1ToolsGet({});
                if (toolsResponse.error || !toolsResponse.data) {
                    setToolsError(detailFromError(toolsResponse.error, "Couldn't load your tools"));
                    return;
                }
                setTools(toolsResponse.data);
            } catch {
                setToolsError(NETWORK_ERROR);
            }
        })();
        if (!skillUuid) return;
        void (async () => {
            try {
                const response = await getSkillApiV1SkillsSkillUuidGet({ path: { skill_uuid: skillUuid } });
                if (response.error || !response.data) {
                    setLoadError(skillError(response.error, "Couldn't load this skill").message);
                    return;
                }
                applySkill(response.data);
            } catch {
                setLoadError(NETWORK_ERROR);
            } finally {
                setLoading(false);
            }
        })();
    }, [authLoading, user, skillUuid, applySkill]);

    const save = async () => {
        setShowErrors(true);
        setFormError(null);
        if (hasErrors(errors)) {
            setFormError("Fix the highlighted fields, then save again.");
            return;
        }
        setSaving(true);
        try {
            const response = skillUuid
                ? await updateSkillApiV1SkillsSkillUuidPatch({
                      path: { skill_uuid: skillUuid },
                      body: updateBody(draft, baseline),
                  })
                : await createSkillApiV1SkillsPost({ body: createBody(draft) });
            if (response.error || !response.data) {
                const info = skillError(response.error, "Couldn't save the skill");
                if (info.kind === "name_conflict") {
                    setNameConflict({ message: info.message, suggestedName: info.suggestedName });
                } else {
                    setFormError(info.kind === "limit" ? LIMIT_MESSAGE : info.message);
                }
                return;
            }
            setNameConflict(null);
            setShowErrors(false);
            applySkill(response.data);
            toast.success(skillUuid ? "Skill saved" : `Created ${response.data.name}`);
            if (!skillUuid) router.replace(`/skills/${response.data.skill_uuid}`);
        } catch {
            setFormError(NETWORK_ERROR);
        } finally {
            setSaving(false);
        }
    };

    const exportZip = async () => {
        if (!skill) return;
        setExporting(true);
        const problem = await downloadSkillZip(skill.skill_uuid, skill.name);
        setExporting(false);
        if (problem) toast.error(problem);
    };

    const title = skillUuid ? (skill?.name ?? "Skill") : "New skill";

    return (
        <div className="page-body">
            <div className="w-full max-w-4xl space-y-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                        <Link
                            href="/skills"
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                        >
                            <ArrowLeft className="size-3.5" aria-hidden />
                            Skills
                        </Link>
                        <div className="flex flex-wrap items-center gap-2">
                            <h1 className="truncate font-mono text-lg font-semibold">{title}</h1>
                            {skill && (
                                <StatusPill tone={skill.source_library_uuid ? "info" : "mute"}>
                                    {sourceLabel(skill)}
                                </StatusPill>
                            )}
                            {skill?.is_modified && <StatusPill tone="warn">Modified</StatusPill>}
                            {dirty && !readOnly && <StatusPill tone="warn">Unsaved changes</StatusPill>}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {skill?.update_available && (
                            <Button
                                variant="soft"
                                onClick={() => setUpdateOpen(true)}
                                disabled={dirty}
                                title={dirty ? "Save or discard your edits first" : undefined}
                            >
                                <RefreshCw aria-hidden />
                                Update available
                            </Button>
                        )}
                        {skill && (
                            <Button variant="soft" onClick={() => void exportZip()} disabled={exporting}>
                                {exporting ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
                                Export
                            </Button>
                        )}
                        {!readOnly && (
                            <Button onClick={() => void save()} disabled={saving || (skillUuid !== null && !dirty)}>
                                {saving ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
                                {skillUuid ? "Save" : "Create skill"}
                            </Button>
                        )}
                    </div>
                </div>

                {readOnly && (
                    <p className="text-sm text-muted-foreground">
                        You can view this skill. Ask a workspace admin or developer to change it.
                    </p>
                )}
                {skill?.source_library_uuid && !skill.is_modified && !readOnly && (
                    <p className="text-xs text-muted-foreground">
                        Copied from the library. Editing it marks it as modified, and library updates then need your
                        confirmation.
                    </p>
                )}
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
                        mode="workspace"
                        draft={draft}
                        onChange={(next) => {
                            setDraft(next);
                            if (nameConflict && next.name !== draft.name) setNameConflict(null);
                        }}
                        errors={errors}
                        showErrors={showErrors}
                        readOnly={readOnly}
                        tools={tools}
                        toolsError={toolsError}
                        nameConflict={nameConflict}
                    />
                )}
            </div>

            <UpdateDialog
                skill={updateOpen ? skill : null}
                canApply={canWrite}
                onOpenChange={setUpdateOpen}
                onApplied={(updated) => {
                    applySkill(updated);
                    setUpdateOpen(false);
                }}
            />
        </div>
    );
}
