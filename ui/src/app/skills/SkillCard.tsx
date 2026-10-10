"use client";

import { Download, Loader2, Pencil, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";

import type { SkillSummaryResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";

export type SkillAction = "export" | "archive" | "update";

interface SkillCardProps {
    skill: SkillSummaryResponse;
    canWrite: boolean;
    busy: SkillAction | null;
    onAction: (action: SkillAction) => void;
}

export function sourceLabel(skill: Pick<SkillSummaryResponse, "source_library_uuid" | "source_version">): string {
    if (!skill.source_library_uuid) return "Custom";
    return skill.source_version ? `From library v${skill.source_version}` : "From library";
}

export function allowedToolsLabel(allowed: readonly string[] | null): string | null {
    if (allowed === null) return null;
    if (allowed.length === 0) return "No other tools while loaded";
    return `Limited to ${allowed.length} ${allowed.length === 1 ? "tool" : "tools"} while loaded`;
}

export function SkillCard({ skill, canWrite, busy, onAction }: SkillCardProps) {
    const tools = allowedToolsLabel(skill.allowed_tool_uuids);
    return (
        <Panel padding="sm" className="flex flex-col gap-3 sm:flex-row sm:items-start" data-testid="skill-card">
            <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                    <Link
                        href={`/skills/${skill.skill_uuid}`}
                        className="font-mono text-sm font-semibold text-foreground hover:underline"
                    >
                        {skill.name}
                    </Link>
                    <StatusPill tone={skill.source_library_uuid ? "info" : "mute"}>{sourceLabel(skill)}</StatusPill>
                    {skill.is_modified && <StatusPill tone="warn">Modified</StatusPill>}
                    {skill.update_available && <StatusPill tone="live">Update available</StatusPill>}
                </div>
                <p className="line-clamp-2 text-sm text-ink-2">{skill.description}</p>
                {tools && <p className="text-xs text-muted-foreground">{tools}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
                {skill.update_available && (
                    <Button size="sm" variant="soft" onClick={() => onAction("update")}>
                        <RefreshCw aria-hidden />
                        {canWrite ? "Review update" : "View update"}
                    </Button>
                )}
                <Button size="sm" variant="ghost" asChild>
                    <Link href={`/skills/${skill.skill_uuid}`} aria-label={`${canWrite ? "Edit" : "View"} ${skill.name}`}>
                        <Pencil aria-hidden />
                        {canWrite ? "Edit" : "View"}
                    </Link>
                </Button>
                <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onAction("export")}
                    disabled={busy === "export"}
                    aria-label={`Export ${skill.name}`}
                >
                    {busy === "export" ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
                    Export
                </Button>
                {canWrite && (
                    <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        onClick={() => onAction("archive")}
                        disabled={busy === "archive"}
                        aria-label={`Archive ${skill.name}`}
                    >
                        <Trash2 aria-hidden />
                        Archive
                    </Button>
                )}
            </div>
        </Panel>
    );
}
