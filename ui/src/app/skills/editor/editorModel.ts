import type {
    CreateSkillRequest,
    LibrarySkillResponse,
    SkillFileBody,
    SkillResponse,
    UpdateLibrarySkillRequest,
    UpdateSkillRequest,
} from "@/client/types.gen";

import { type DraftErrors, validateDraft } from "../validation";

export interface EditorFile {
    /** Client-side identity, stable across renames. */
    id: string;
    path: string;
    content: string;
}

let nextId = 0;
export function newFileId(): string {
    nextId += 1;
    return `file-${nextId}`;
}

export interface EditorDraft {
    name: string;
    description: string;
    body_md: string;
    files: EditorFile[];
    /** Workspace skills only: null = no restriction. */
    allowed_tool_uuids: string[] | null;
    /** Library skills only. */
    category: string;
}

export const EMPTY_BODY = `# Steps

1. Explain what the agent should do when this skill applies.
2. Keep each step short so it is easy to follow mid-call.
`;

export function emptyDraft(): EditorDraft {
    return { name: "", description: "", body_md: EMPTY_BODY, files: [], allowed_tool_uuids: null, category: "" };
}

/**
 * The editable draft for a saved skill. `previousFiles` (the draft being
 * replaced, e.g. after a save) lends its ids to files with the same path, so
 * the file that was open stays selected.
 */
export function draftFromSkill(
    skill: SkillResponse | LibrarySkillResponse,
    previousFiles: readonly EditorFile[] = [],
): EditorDraft {
    const idByPath = new Map(previousFiles.map((f) => [f.path.trim(), f.id]));
    return {
        name: skill.name,
        description: skill.description,
        body_md: skill.body_md,
        files: skill.files.map((f) => ({ id: idByPath.get(f.path) ?? newFileId(), path: f.path, content: f.content })),
        allowed_tool_uuids: "allowed_tool_uuids" in skill ? (skill.allowed_tool_uuids ?? null) : null,
        category: "category" in skill ? (skill.category ?? "") : "",
    };
}

function filesBody(files: readonly EditorFile[]): SkillFileBody[] {
    return files.map((f) => ({ path: f.path.trim(), content: f.content }));
}

function sameFiles(a: readonly EditorFile[], b: readonly EditorFile[]): boolean {
    return JSON.stringify(filesBody(a)) === JSON.stringify(filesBody(b));
}

function sameTools(a: readonly string[] | null, b: readonly string[] | null): boolean {
    if (a === null || b === null) return a === b;
    return a.length === b.length && [...a].sort().join() === [...b].sort().join();
}

export function isDirty(draft: EditorDraft, baseline: EditorDraft): boolean {
    return (
        draft.name !== baseline.name ||
        draft.description !== baseline.description ||
        draft.body_md !== baseline.body_md ||
        draft.category !== baseline.category ||
        !sameFiles(draft.files, baseline.files) ||
        !sameTools(draft.allowed_tool_uuids, baseline.allowed_tool_uuids)
    );
}

export function draftErrors(draft: EditorDraft): DraftErrors {
    return validateDraft({ ...draft, files: filesBody(draft.files) });
}

export function createBody(draft: EditorDraft): CreateSkillRequest {
    return {
        name: draft.name,
        description: draft.description.trim(),
        body_md: draft.body_md,
        files: filesBody(draft.files),
        allowed_tool_uuids: draft.allowed_tool_uuids,
    };
}

/** Only the changed fields, so an unchanged body never marks a copy modified. */
export function updateBody(draft: EditorDraft, baseline: EditorDraft): UpdateSkillRequest {
    const body: UpdateSkillRequest = {};
    if (draft.name !== baseline.name) body.name = draft.name;
    if (draft.description !== baseline.description) body.description = draft.description.trim();
    if (draft.body_md !== baseline.body_md) body.body_md = draft.body_md;
    if (!sameFiles(draft.files, baseline.files)) body.files = filesBody(draft.files);
    if (!sameTools(draft.allowed_tool_uuids, baseline.allowed_tool_uuids)) {
        body.allowed_tool_uuids = draft.allowed_tool_uuids;
    }
    return body;
}

export function libraryUpdateBody(draft: EditorDraft, baseline: EditorDraft): UpdateLibrarySkillRequest {
    const body: UpdateLibrarySkillRequest = {};
    if (draft.name !== baseline.name) body.name = draft.name;
    if (draft.description !== baseline.description) body.description = draft.description.trim();
    if (draft.body_md !== baseline.body_md) body.body_md = draft.body_md;
    if (!sameFiles(draft.files, baseline.files)) body.files = filesBody(draft.files);
    if (draft.category !== baseline.category) body.category = draft.category.trim() || null;
    return body;
}
