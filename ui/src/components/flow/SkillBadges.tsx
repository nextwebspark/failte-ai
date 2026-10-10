"use client";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { Badge } from "@/components/ui/badge";

interface SkillBadgesProps {
    /** `skill_uuids`: null/undefined lists all skills, `[]` none. */
    skillUuids?: string[] | null;
    preloadSkillUuids?: string[] | null;
}

/** Canvas summary of a step's skills; renders nothing for the default (all skills). */
export function SkillBadges({ skillUuids, preloadSkillUuids }: SkillBadgesProps) {
    const { skills, skillsError } = useWorkflow();
    const names = new Map((skills ?? []).map((s) => [s.skill_uuid, s.name]));
    const label = (uuid: string) =>
        names.get(uuid) ?? (skillsError ? "skill" : skills === undefined ? "…" : "archived skill");
    const preload = preloadSkillUuids ?? [];

    return (
        <div className="flex flex-wrap gap-1">
            {skillUuids && skillUuids.length === 0 && (
                <Badge variant="outline" className="text-xs text-muted-foreground">
                    No skills
                </Badge>
            )}
            {(skillUuids ?? []).map((uuid) => (
                <Badge key={uuid} variant="outline" className="font-mono text-xs">
                    {label(uuid)}
                </Badge>
            ))}
            {preload.map((uuid) => (
                <Badge key={`preload-${uuid}`} variant="outline" className="font-mono text-xs" title="Preloaded">
                    {label(uuid)} · preloaded
                </Badge>
            ))}
        </div>
    );
}
