import { BookOpen } from "lucide-react";

import { StatusPill } from "@/components/ui/status-pill";

/** One `gathered_context.skills_loaded` record written by the engine. */
export interface SkillLoadRecord {
    name: string;
    node: string | null;
    via: string | null;
    at: string | null;
}

function text(value: unknown): string | null {
    return typeof value === "string" && value ? value : null;
}

/** Tolerant parse: ignores entries without a skill name. */
export function skillsLoadedFrom(gatheredContext: Record<string, unknown> | null | undefined): SkillLoadRecord[] {
    const raw = gatheredContext?.skills_loaded;
    if (!Array.isArray(raw)) return [];
    return raw.flatMap((entry): SkillLoadRecord[] => {
        if (!entry || typeof entry !== "object") return [];
        const record = entry as Record<string, unknown>;
        const name = text(record.name);
        if (!name) return [];
        return [{ name, node: text(record.node), via: text(record.via), at: text(record.at) }];
    });
}

function formatTime(iso: string | null): string | null {
    if (!iso) return null;
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? null : date.toLocaleTimeString();
}

/** Which skills the agent loaded (or had preloaded) during the run. */
export function SkillsLoadedSection({ gatheredContext }: { gatheredContext: Record<string, unknown> | null }) {
    const records = skillsLoadedFrom(gatheredContext);
    if (records.length === 0) return null;
    return (
        <section className="rounded-xl border border-border bg-muted/20 p-4" aria-labelledby="skills-loaded-title">
            <h2 id="skills-loaded-title" className="mb-3 flex items-center gap-2 text-sm font-semibold">
                <BookOpen className="size-4" aria-hidden />
                Skills used
            </h2>
            <ul className="space-y-2">
                {records.map((record, index) => (
                    <li key={`${record.name}-${index}`} className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="font-mono font-medium">{record.name}</span>
                        <StatusPill tone={record.via === "preload" ? "mute" : "info"}>
                            {record.via === "preload" ? "Preloaded" : "Loaded"}
                        </StatusPill>
                        {record.node && <span className="text-muted-foreground">in {record.node}</span>}
                        {formatTime(record.at) && (
                            <span className="font-mono text-xs text-ink-3">{formatTime(record.at)}</span>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    );
}
