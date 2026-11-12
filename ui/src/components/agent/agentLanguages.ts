/**
 * The languages an agent speaks (the `agent_languages` fact; see
 * api/services/workflow/agent_languages.py). English is always on. The value
 * is the languages' English names, comma-separated, English first
 * ("English, Polish"); English only is saved as "" so the prompt's fallback
 * ("English") applies.
 */
export const AGENT_LANGUAGES_KEY = "agent_languages";

export const AGENT_LANGUAGES = [
    "English",
    "Irish",
    "Polish",
    "Lithuanian",
    "Romanian",
    "Portuguese",
    "Spanish",
    "French",
    "Ukrainian",
    "Chinese",
    "Arabic",
] as const;

export type AgentLanguage = (typeof AGENT_LANGUAGES)[number];

/** The languages in a stored value, in the offered order; English always. Unknown names are dropped. */
export function parseAgentLanguages(value: string | null | undefined): AgentLanguage[] {
    const given = new Set(
        (value ?? "")
            .split(",")
            .map((part) => part.trim().toLowerCase())
            .filter(Boolean),
    );
    return AGENT_LANGUAGES.filter((name) => name === "English" || given.has(name.toLowerCase()));
}

/** The value to save: "" for English only, else "English, Polish". */
export function serializeAgentLanguages(languages: readonly string[]): string {
    const chosen = parseAgentLanguages(languages.join(","));
    return chosen.length > 1 ? chosen.join(", ") : "";
}

/** The value with one language switched on or off (English stays on). */
export function toggleAgentLanguage(value: string | null | undefined, language: AgentLanguage): string {
    if (language === "English") return serializeAgentLanguages(parseAgentLanguages(value));
    const current = parseAgentLanguages(value);
    const next = current.includes(language) ? current.filter((l) => l !== language) : [...current, language];
    return serializeAgentLanguages(next);
}
