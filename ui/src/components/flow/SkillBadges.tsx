"use client";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { NodeChip } from "@/components/flow/NodeChip";

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
        <>
            {skillUuids && skillUuids.length === 0 && <NodeChip>no skills</NodeChip>}
            {(skillUuids ?? []).map((uuid) => (
                <NodeChip key={uuid} title={label(uuid)}>
                    skill: {label(uuid)}
                </NodeChip>
            ))}
            {preload.map((uuid) => (
                <NodeChip key={`preload-${uuid}`} title={`${label(uuid)} (preloaded)`}>
                    skill: {label(uuid)} · preloaded
                </NodeChip>
            ))}
        </>
    );
}
