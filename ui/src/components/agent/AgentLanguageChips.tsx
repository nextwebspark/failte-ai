"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

import { AGENT_LANGUAGES, parseAgentLanguages, toggleAgentLanguage } from "./agentLanguages";

/**
 * "Languages your agent speaks": one switch per offered language, English
 * always on. Used on What your agent knows and in the Create agent wizard.
 */
export function AgentLanguageChips({
    id,
    value,
    onChange,
    disabled,
    showVoiceNote = true,
}: {
    id?: string;
    value: string;
    onChange: (value: string) => void;
    disabled?: boolean;
    showVoiceNote?: boolean;
}) {
    const on = new Set<string>(parseAgentLanguages(value));
    return (
        <div className="flex flex-col gap-2">
            <ul id={id} aria-label="Languages your agent speaks" className="flex flex-wrap gap-2">
                {AGENT_LANGUAGES.map((language) => {
                    const english = language === "English";
                    const selected = on.has(language);
                    return (
                        <li key={language}>
                            <button
                                type="button"
                                aria-pressed={selected}
                                aria-label={english ? "English (always on)" : language}
                                disabled={disabled || english}
                                onClick={() => onChange(toggleAgentLanguage(value, language))}
                                className={cn(
                                    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-caption font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed",
                                    selected
                                        ? "border-brand bg-brand-dim text-brand"
                                        : "border-line bg-panel text-foreground hover:bg-panel-2",
                                    disabled && !english && "opacity-60",
                                )}
                            >
                                {selected && <Check className="size-3.5" aria-hidden />}
                                {language}
                            </button>
                        </li>
                    );
                })}
            </ul>
            <p className="text-caption text-ink-3">
                English is always on. If a caller speaks a language that isn&apos;t on, your agent says one short
                line in their language offering a member of staff or a call back, and carries on in English.
            </p>
            {showVoiceNote && (
                <p className="text-caption text-ink-3">
                    Answers in other languages are read in your agent&apos;s own voice. On the standard voice, your
                    agent hears and speaks these languages itself. If your agent uses a separate speech-to-text and
                    voice, other languages may be understood less well and read with an English accent: try a test
                    call first.
                </p>
            )}
        </div>
    );
}
