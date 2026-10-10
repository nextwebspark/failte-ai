/**
 * Ways to narrow the voice cards. Google describes each Gemini Live / Chirp 3
 * HD voice with a gender and one style word ("Kore" → "Firm"); the tones
 * below group those words so customers can shortlist voices by feel.
 */

export interface VoiceTone {
    id: string;
    label: string;
    styles: readonly string[];
}

export const VOICE_TONES: readonly VoiceTone[] = [
    {
        id: "professional",
        label: "Calm & professional",
        styles: ["Informative", "Firm", "Clear", "Even", "Smooth", "Knowledgeable", "Mature"],
    },
    {
        id: "warm",
        label: "Warm & friendly",
        styles: ["Friendly", "Warm", "Gentle", "Soft", "Easy-going", "Casual", "Breezy"],
    },
    {
        id: "energetic",
        label: "Energetic & upbeat",
        styles: ["Upbeat", "Excitable", "Bright", "Lively", "Youthful", "Forward"],
    },
    {
        id: "distinctive",
        label: "Distinctive",
        styles: ["Breathy", "Gravelly"],
    },
];

/** The tone a voice's style word belongs to, if any. */
export function voiceTone(style: string | null | undefined): string | null {
    if (!style) return null;
    return VOICE_TONES.find((tone) => tone.styles.includes(style))?.id ?? null;
}

const ACCENT_LABELS: Record<string, string> = {
    "en-US": "American",
    "en-GB": "British",
    "en-AU": "Australian",
    "en-IN": "Indian",
    "es-ES": "Spain",
    "es-US": "United States",
    "fr-FR": "France",
    "fr-CA": "Canada",
    "nl-NL": "Netherlands",
    "nl-BE": "Belgium",
};

let regionNames: Intl.DisplayNames | null | undefined;

/** Short accent name for a locale: "en-GB" → "British", "pt-BR" → "Brazil". */
export function accentLabel(locale: string): string {
    if (ACCENT_LABELS[locale]) return ACCENT_LABELS[locale];
    const region = locale.split("-")[1];
    if (!region) return locale;
    if (regionNames === undefined) {
        try {
            regionNames = new Intl.DisplayNames(["en"], { type: "region" });
        } catch {
            regionNames = null;
        }
    }
    try {
        return regionNames?.of(region) ?? region;
    } catch {
        return region;
    }
}

/** Locales grouped by base language: "en" → ["en-AU", "en-GB", "en-IN", "en-US"]. */
export function localesByLanguage(locales: readonly string[]): Map<string, string[]> {
    const groups = new Map<string, string[]>();
    for (const locale of locales) {
        const base = locale.split("-")[0];
        groups.set(base, [...(groups.get(base) ?? []), locale]);
    }
    for (const [base, group] of groups) {
        groups.set(base, group.sort((a, b) => accentLabel(a).localeCompare(accentLabel(b))));
    }
    return groups;
}
