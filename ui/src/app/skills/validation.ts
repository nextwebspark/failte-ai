/**
 * Client-side checks that mirror `api/services/skills/validation.py`, so the
 * editor can flag problems before saving. The server stays the authority:
 * anything that slips through comes back as a 422 with a readable message.
 */

export const NAME_MAX = 64;
export const DESCRIPTION_MAX = 1024;
export const BODY_MAX_BYTES = 64 * 1024;
export const MAX_FILES = 20;
export const FILE_MAX_BYTES = 256 * 1024;
export const FILES_TOTAL_MAX_BYTES = 1024 * 1024;
export const PATH_MAX = 255;
export const PATH_MAX_DEPTH = 8;
export const CATEGORY_MAX = 64;
export const MAX_ALLOWED_TOOLS = 50;
/** Active skills per workspace (`MAX_ACTIVE_SKILLS` on the server). */
export const MAX_ACTIVE_SKILLS = 50;
export const SKILL_FILE_NAME = "SKILL.md";

const NAME_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const CONTROL = /[\x00-\x1f\x7f]/;
const TEXT_CONTROL = /[\x00-\x08\x0b\x0c\x0e-\x1f]/;
const LINE_CONTROL = /[\x00-\x1f\x7f-\x9f\u2028\u2029]/;
const XML_TAG = /<\/?[A-Za-z][\w:.-]*(\s[^<>]*)?\/?>/;

const LINE_BREAK = /\r\n?|\u2028|\u2029/g;
const encoder = new TextEncoder();

/** Every line terminator as "\n", as the server stores bodies and files. */
export function normalizeNewlines(text: string): string {
    return text.replace(LINE_BREAK, "\n");
}

export function byteLength(text: string): number {
    return encoder.encode(text).length;
}

export function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
}

/** Returns an error message, or null when the name is valid. */
export function nameError(name: string): string | null {
    if (!name) return "Name is required";
    if (name.length > NAME_MAX) return `Name must be at most ${NAME_MAX} characters`;
    if (!NAME_PATTERN.test(name)) {
        return "Use lowercase letters, digits and single hyphens, not starting or ending with a hyphen (e.g. returns-policy)";
    }
    return null;
}

/** Best-effort conversion of free text into a valid skill name. */
export function toSkillName(text: string): string {
    return text
        .toLowerCase()
        .normalize("NFKD")
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, NAME_MAX)
        .replace(/-+$/g, "");
}

export function descriptionError(description: string): string | null {
    const value = description.trim();
    if (!value) return "Description is required";
    if (value.length > DESCRIPTION_MAX) return `Description must be at most ${DESCRIPTION_MAX} characters`;
    if (LINE_CONTROL.test(value)) return "Description must be a single line";
    if (XML_TAG.test(value)) return "Description must not contain XML-style tags like <tag>";
    return null;
}

export function bodyError(body: string): string | null {
    const value = normalizeNewlines(body);
    if (!value.trim()) return "Instructions are required";
    if (byteLength(value) > BODY_MAX_BYTES) return `Instructions must be at most ${BODY_MAX_BYTES / 1024} KB`;
    if (TEXT_CONTROL.test(value)) return "Instructions contain unsupported control characters";
    return null;
}

/**
 * A relative POSIX path inside the skill folder. Rejects absolute paths, drive
 * letters, backslashes, empty, `.` or `..` segments, hidden files and
 * `SKILL.md` at the root (that is the instructions).
 */
export function pathError(rawPath: string): string | null {
    const path = rawPath.normalize("NFC");
    if (!path) return "File path is required";
    if (path.length > PATH_MAX) return `File path must be at most ${PATH_MAX} characters`;
    if (CONTROL.test(path)) return "File path contains control characters";
    if (path.includes("\\")) return "Use '/' to separate folders, not '\\'";
    if (path.startsWith("/") || /^[A-Za-z]:/.test(path)) return "File path must be relative (no leading '/')";
    const segments = path.split("/");
    if (segments.length > PATH_MAX_DEPTH) return `Folders can be nested at most ${PATH_MAX_DEPTH} levels`;
    for (const segment of segments) {
        if (segment === "" || segment === "." || segment === "..") {
            return "File path must not contain empty, '.' or '..' parts";
        }
        if (segment.startsWith(".")) return "Hidden files and folders (starting with '.') are not allowed";
    }
    if (path.toLowerCase() === SKILL_FILE_NAME.toLowerCase()) {
        return "SKILL.md holds the instructions; pick another file name";
    }
    return null;
}

export interface SkillFileDraft {
    path: string;
    content: string;
}

export interface FileIssue {
    /** Index into the files list, or null for a whole-set problem. */
    index: number | null;
    message: string;
}

export function fileIssues(files: readonly SkillFileDraft[]): FileIssue[] {
    const issues: FileIssue[] = [];
    const seen = new Set<string>();
    let total = 0;
    files.forEach((file, index) => {
        const pathProblem = pathError(file.path);
        if (pathProblem) {
            issues.push({ index, message: pathProblem });
        } else {
            const key = file.path.normalize("NFC").toLowerCase();
            if (seen.has(key)) issues.push({ index, message: "Another file already uses this path" });
            seen.add(key);
        }
        const content = normalizeNewlines(file.content);
        const size = byteLength(content);
        total += size;
        if (size > FILE_MAX_BYTES) issues.push({ index, message: `File is larger than ${FILE_MAX_BYTES / 1024} KB` });
        if (TEXT_CONTROL.test(content)) issues.push({ index, message: "Only text files are supported" });
    });
    if (files.length > MAX_FILES) issues.push({ index: null, message: `A skill can have at most ${MAX_FILES} files` });
    if (total > FILES_TOTAL_MAX_BYTES) {
        issues.push({ index: null, message: `Files must total at most ${FILES_TOTAL_MAX_BYTES / 1024} KB` });
    }
    return issues;
}

export function categoryError(category: string): string | null {
    const value = category.trim();
    if (value.length > CATEGORY_MAX) return `Category must be at most ${CATEGORY_MAX} characters`;
    if (LINE_CONTROL.test(value)) return "Category must be a single line";
    return null;
}

export interface SkillDraft {
    name: string;
    description: string;
    body_md: string;
    files: SkillFileDraft[];
}

export interface DraftErrors {
    name: string | null;
    description: string | null;
    body: string | null;
    files: FileIssue[];
}

export function validateDraft(draft: SkillDraft): DraftErrors {
    return {
        name: nameError(draft.name),
        description: descriptionError(draft.description),
        body: bodyError(draft.body_md),
        files: fileIssues(draft.files),
    };
}

export function hasErrors(errors: DraftErrors): boolean {
    return Boolean(errors.name || errors.description || errors.body || errors.files.length > 0);
}
