import { detailFromError, errorCodeFromError } from "@/lib/apiError";

export const NETWORK_ERROR = "Couldn't reach the server. Check your connection and try again.";

export type SkillErrorKind = "limit" | "name_conflict" | "modified" | "invalid" | "not_found" | "other";

export interface SkillErrorInfo {
    kind: SkillErrorKind;
    message: string;
    /** For a name conflict: a free name the server suggests. */
    suggestedName: string | null;
}

const KIND_BY_CODE: Record<string, SkillErrorKind> = {
    skill_limit_reached: "limit",
    skill_name_conflict: "name_conflict",
    skill_modified: "modified",
    skill_invalid: "invalid",
    skill_not_found: "not_found",
    library_skill_not_found: "not_found",
};

/** Normalizes a `{ error }` from the skills API into something the UI can branch on. */
export function skillError(error: unknown, fallback: string): SkillErrorInfo {
    const code = errorCodeFromError(error);
    const kind = (code && KIND_BY_CODE[code]) || "other";
    const suggested = (error as { suggested_name?: unknown } | null)?.suggested_name;
    return {
        kind,
        message: detailFromError(error, fallback),
        suggestedName: typeof suggested === "string" && suggested ? suggested : null,
    };
}
