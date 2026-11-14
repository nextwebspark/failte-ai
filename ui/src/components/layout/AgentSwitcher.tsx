"use client";

import { Check, ChevronsUpDown, GitBranch, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { agentLineLabel, agentLineShort, agentNameParts } from "@/components/dashboard/dashboardView";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { cn } from "@/lib/utils";

import { AGENT_PAGES, agentHref, agentIdFromPath, agentSectionFor, isAgentCallsRoute } from "./agentNav";
import { initialsOf } from "./memberIdentity";
import { useSelectedAgent, type WorkspaceAgent } from "./workspaceAgents";

/**
 * The top of the menu's Agent section: which agent its rows open, and the
 * number that rings it ("Answers 01 555 7000"). With several agents it is a
 * menu to pick another; on an agent's screen, picking one opens the same
 * screen for that agent. With one agent it only names it; with none it
 * offers to create one.
 */
export function AgentSwitcher({ collapsed, onNavigate }: { collapsed: boolean; onNavigate: () => void }) {
  const { agents, selected, select } = useSelectedAgent();
  const { can, role } = useOrgConfig();
  const pathname = usePathname();
  const router = useRouter();
  const mayCreate = role !== null && can("agents:write");

  if (agents === null) {
    // Hold the row's height while the agents load.
    return <div aria-hidden className={cn("mx-2 mb-1 h-[46px] rounded-[10px] bg-panel-2/60", collapsed && "mx-1 h-8")} />;
  }

  if (agents.length === 0 && !selected) {
    if (collapsed || !mayCreate) {
      return collapsed ? null : <p className="px-4 pb-1 text-caption text-ink-3">No agent yet</p>;
    }
    return (
      <Link
        href="/workflow/create"
        onClick={onNavigate}
        className="mx-2 mb-1 flex items-center gap-2.5 rounded-[10px] border border-dashed border-line px-2.5 py-2 text-sm font-medium text-brand outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <Plus className="size-4" aria-hidden />
        Create your agent
      </Link>
    );
  }

  const current = selected ?? agents[0];
  const several = agents.length > 1 || !agents.some((a) => a.id === current.id);

  const pick = (agent: WorkspaceAgent) => {
    select(agent.id);
    // On an agent's screen, open the same screen for the agent picked.
    const onAgent = agentIdFromPath(pathname);
    if (onAgent === null || onAgent === agent.id) return;
    const page = isAgentCallsRoute(pathname) ? null : agentSectionFor(pathname);
    const allowed = page && (!page.requires || can(page.requires)) ? page : AGENT_PAGES[0];
    onNavigate();
    router.push(agentHref(agent.id, allowed.segment, allowed.hash));
  };

  const card = (
    <>
      <span
        aria-hidden
        className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-sky-dim text-[12px] font-bold text-sky"
      >
        {initialsOf(agentNameParts(current.name).title, "A")}
      </span>
      <span className={cn("min-w-0 flex-1 text-left leading-tight", collapsed && "sr-only")} title={current.name}>
        <span className="block truncate text-caption font-semibold text-foreground">
          {agentNameParts(current.name).title}
        </span>
        <span className="block truncate text-meta text-ink-3">{agentLineShort(current)}</span>
      </span>
    </>
  );
  const boxClass = cn(
    "mx-2 mb-1 flex items-center gap-2.5 rounded-[10px] border border-line px-2.5 py-2",
    collapsed && "mx-1 justify-center border-0 p-0",
  );

  if (!several) {
    const box = (
      <div className={boxClass} data-testid="agent-switcher">
        {card}
      </div>
    );
    return collapsed ? (
      <Tooltip>
        <TooltipTrigger asChild>{box}</TooltipTrigger>
        <TooltipContent side="right">{current.name}</TooltipContent>
      </Tooltip>
    ) : (
      box
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          boxClass,
          "w-[calc(100%-1rem)] outline-none transition-colors hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50",
          collapsed && "w-auto",
        )}
        aria-label={`Agent: ${current.name}. Pick another agent`}
        data-testid="agent-switcher"
      >
        {card}
        {!collapsed && <ChevronsUpDown className="size-3.5 shrink-0 text-ink-3" aria-hidden />}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side={collapsed ? "right" : "bottom"} className="w-72">
        <DropdownMenuLabel className="text-caption font-normal text-ink-3">
          Each number rings one agent
        </DropdownMenuLabel>
        {agents.map((agent) => (
          <DropdownMenuItem key={agent.id} onSelect={() => pick(agent)} className="flex items-start gap-2">
            <Check
              aria-hidden
              className={cn("mt-0.5 size-4 shrink-0", agent.id === current.id ? "text-brand" : "invisible")}
            />
            <span className="flex min-w-0 flex-col">
              <span className="font-medium text-foreground">{agentNameParts(agent.name).title}</span>
              <span className="text-caption text-ink-3">
                {[agentNameParts(agent.name).kind, agentLineLabel(agent)].filter(Boolean).join(" · ")}
              </span>
            </span>
            {agent.id === current.id && <span className="sr-only">(selected)</span>}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/workflow" onClick={onNavigate}>
            <GitBranch aria-hidden />
            All voice agents
          </Link>
        </DropdownMenuItem>
        {mayCreate && (
          <DropdownMenuItem asChild>
            <Link href="/workflow/create" onClick={onNavigate}>
              <Plus aria-hidden />
              Create agent
            </Link>
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
