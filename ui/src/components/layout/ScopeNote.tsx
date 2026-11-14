import { Bot, Building2, UserRound } from "lucide-react";

import { agentNameParts } from "@/components/dashboard/dashboardView";
import { cn } from "@/lib/utils";

/** Who a setting reaches: the whole workspace, one agent, or only you. */
export type SettingScope = "workspace" | "agent" | "you";

/** The words of the note, so screens and tests say the same thing. */
export function scopeLabel(scope: SettingScope, agentName?: string | null): string {
  if (scope === "workspace") return "Workspace setting · same for every agent";
  if (scope === "you") return "Only for you";
  const name = agentName ? agentNameParts(agentName).title : "";
  return name ? `Only for ${name}` : "Only for this agent";
}

const ICONS = { workspace: Building2, agent: Bot, you: UserRound } as const;

/**
 * A small note beside a screen's title saying who its settings reach, so a
 * workspace setting is never mistaken for an agent's, or the other way round.
 */
export function ScopeNote({
  scope,
  agentName,
  className,
}: {
  scope: SettingScope;
  agentName?: string | null;
  className?: string;
}) {
  const Icon = ICONS[scope];
  return (
    <span
      data-scope={scope}
      className={cn(
        "inline-flex max-w-full shrink-0 items-center gap-1 rounded-full border border-line bg-panel-2 px-2 py-0.5 text-meta font-medium text-ink-2",
        className,
      )}
    >
      <Icon className="size-3 shrink-0 text-ink-3" aria-hidden />
      <span className="truncate">{scopeLabel(scope, agentName)}</span>
    </span>
  );
}
