"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import type { SkillSummaryResponse } from "@/client/types.gen";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

/**
 * `skill_uuids` is tri-state on the backend:
 * - unset (null/undefined): the step lists every active workspace skill;
 * - `[]`: the step lists no skills;
 * - a list: only those skills.
 */
export type SkillScope = "all" | "none" | "selected";

export function scopeOf(value: readonly string[] | null | undefined): SkillScope {
    if (value === null || value === undefined) return "all";
    return value.length === 0 ? "none" : "selected";
}

/** The value to store for a scope; "selected" keeps the current picks. */
export function valueForScope(scope: SkillScope, current: readonly string[] | null | undefined): string[] | undefined {
    if (scope === "all") return undefined;
    if (scope === "none") return [];
    return [...(current ?? [])];
}

interface SkillChecklistProps {
    idPrefix: string;
    skills: SkillSummaryResponse[];
    selected: readonly string[];
    onToggle: (uuid: string, checked: boolean) => void;
    disabled?: boolean;
    /** The skills list failed to load. */
    loadError?: boolean;
    labelledBy: string;
}

function SkillChecklist({ idPrefix, skills, selected, onToggle, disabled, loadError, labelledBy }: SkillChecklistProps) {
    const known = new Set(skills.map((s) => s.skill_uuid));
    const missing = selected.filter((uuid) => !known.has(uuid));
    const errorNotice = loadError ? (
        <p className="text-xs text-destructive" role="alert">
            Couldn&apos;t load your skills. Selected skills show by ID; close and reopen this editor to retry.
        </p>
    ) : null;
    if (skills.length === 0 && missing.length === 0) {
        if (errorNotice) return errorNotice;
        return (
            <div className="space-y-2 rounded-md border p-3 text-sm text-muted-foreground">
                <p>This workspace has no skills yet.</p>
                <Link href="/skills" target="_blank" className="inline-flex items-center gap-1.5 hover:text-foreground">
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    Add skills
                </Link>
            </div>
        );
    }
    return (
        <div className="space-y-1.5">
            {errorNotice}
            <div className="max-h-[260px] overflow-y-auto rounded-md border" role="group" aria-labelledby={labelledBy}>
                <ul className="divide-y">
                    {skills.map((skill) => {
                        const id = `${idPrefix}-${skill.skill_uuid}`;
                        return (
                            <li key={skill.skill_uuid} className="flex items-start gap-3 p-2.5">
                                <Checkbox
                                    id={id}
                                    checked={selected.includes(skill.skill_uuid)}
                                    onCheckedChange={(checked) => onToggle(skill.skill_uuid, checked === true)}
                                    disabled={disabled}
                                />
                                <label htmlFor={id} className="grid min-w-0 cursor-pointer gap-0.5">
                                    <span className="font-mono text-sm font-medium">{skill.name}</span>
                                    <span className="line-clamp-2 text-xs text-muted-foreground">{skill.description}</span>
                                </label>
                            </li>
                        );
                    })}
                    {missing.map((uuid) => {
                        const id = `${idPrefix}-${uuid}`;
                        return (
                            <li key={uuid} className="flex items-center gap-3 p-2.5">
                                <Checkbox id={id} checked onCheckedChange={() => onToggle(uuid, false)} disabled={disabled} />
                                <label htmlFor={id} className="cursor-pointer text-xs text-muted-foreground">
                                    {loadError ? (
                                        <>Skill <span className="font-mono">{uuid}</span></>
                                    ) : (
                                        <>
                                            Archived or unknown skill <span className="font-mono">{uuid}</span> (ignored on
                                            calls)
                                        </>
                                    )}
                                </label>
                            </li>
                        );
                    })}
                </ul>
            </div>
        </div>
    );
}

function toggled(current: readonly string[], uuid: string, checked: boolean): string[] {
    return checked ? [...current.filter((u) => u !== uuid), uuid] : current.filter((u) => u !== uuid);
}

interface SkillScopeSelectorProps {
    value: string[] | null | undefined;
    onChange: (value: string[] | undefined) => void;
    skills: SkillSummaryResponse[];
    label: string;
    description?: string | null;
    disabled?: boolean;
    loadError?: boolean;
}

/** Which skills a step lists for on-demand loading (`skill_uuids`). */
export function SkillScopeSelector({
    value,
    onChange,
    skills,
    label,
    description,
    disabled,
    loadError,
}: SkillScopeSelectorProps) {
    const baseId = useId();
    const labelId = `${baseId}-label`;
    // Local, so "Selected" with nothing ticked yet doesn't snap to "None".
    const [scope, setScope] = useState<SkillScope>(() => scopeOf(value));
    const selected = value ?? [];

    return (
        <div className="space-y-2">
            <Label id={labelId}>{label}</Label>
            {description && <p className="text-xs text-muted-foreground">{description}</p>}
            <RadioGroup
                value={scope}
                onValueChange={(next) => {
                    const nextScope = next as SkillScope;
                    setScope(nextScope);
                    onChange(valueForScope(nextScope, value));
                }}
                aria-labelledby={labelId}
                className="gap-2"
                disabled={disabled}
            >
                {(
                    [
                        ["all", "All skills (default)", "Lists every active workspace skill, including ones added later."],
                        ["none", "None", "This step doesn't offer skills."],
                        ["selected", "Selected skills", "Only the skills you pick below."],
                    ] as const
                ).map(([option, title, hint]) => (
                    <div key={option} className="flex items-start gap-2">
                        <RadioGroupItem value={option} id={`${baseId}-${option}`} className="mt-0.5" />
                        <Label htmlFor={`${baseId}-${option}`} className="grid gap-0.5 font-normal">
                            <span className="text-sm">{title}</span>
                            <span className="text-xs text-muted-foreground">{hint}</span>
                        </Label>
                    </div>
                ))}
            </RadioGroup>
            {scope === "selected" && (
                <>
                    <SkillChecklist
                        idPrefix={`${baseId}-skill`}
                        labelledBy={labelId}
                        skills={skills}
                        selected={selected}
                        onToggle={(uuid, checked) => onChange(toggled(selected, uuid, checked))}
                        disabled={disabled}
                        loadError={loadError}
                    />
                    {selected.length === 0 && (
                        <p className="text-xs text-muted-foreground" role="status">
                            Nothing selected yet: until you pick one, this step offers no skills.
                        </p>
                    )}
                </>
            )}
        </div>
    );
}

interface PreloadSkillSelectorProps {
    value: string[] | null | undefined;
    onChange: (value: string[] | undefined) => void;
    skills: SkillSummaryResponse[];
    label: string;
    description?: string | null;
    disabled?: boolean;
    loadError?: boolean;
}

/** Skills inlined into a step's prompt from the start (`preload_skill_uuids`). */
export function PreloadSkillSelector({
    value,
    onChange,
    skills,
    label,
    description,
    disabled,
    loadError,
}: PreloadSkillSelectorProps) {
    const baseId = useId();
    const labelId = `${baseId}-label`;
    const selected = value ?? [];
    return (
        <div className="space-y-2">
            <Label id={labelId}>{label}</Label>
            {description && <p className="text-xs text-muted-foreground">{description}</p>}
            <SkillChecklist
                idPrefix={`${baseId}-skill`}
                labelledBy={labelId}
                loadError={loadError}
                skills={skills}
                selected={selected}
                onToggle={(uuid, checked) => {
                    const next = toggled(selected, uuid, checked);
                    onChange(next.length > 0 ? next : undefined);
                }}
                disabled={disabled}
            />
            {selected.length > 0 && (
                <p className="text-xs text-muted-foreground">
                    Preloading skips the load step but adds the full instructions to every turn of this step.
                </p>
            )}
        </div>
    );
}
