"use client";

import { usePathname } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { getWorkflowsSummaryApiV1WorkflowSummaryGet } from "@/client/sdk.gen";
import { useAgentShellOptional } from "@/context/AgentShellContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";

import { agentIdFromPath } from "./agentNav";

/**
 * The workspace's live (not archived) agents, and which one the menu's
 * "Agent" section is showing.
 *
 * The agents are read once when the shell mounts, and again after leaving an
 * agent screen (where agents are created, renamed and archived). Null while
 * loading or when they can't be read.
 *
 * The selected agent: opening any `/workflow/<id>/...` screen selects <id>;
 * otherwise the last one picked in this workspace (remembered in this
 * browser), else the agent a phone number rings, else the first.
 */
export type WorkspaceAgent = {
  id: number;
  name: string;
  /** The numbers that ring this agent now (one number rings one agent). */
  phone_numbers: string[];
};

type WorkspaceAgentsValue = {
  agents: readonly WorkspaceAgent[] | null;
  selected: WorkspaceAgent | null;
  select: (agentId: number) => void;
};

const WorkspaceAgentsContext = createContext<WorkspaceAgentsValue>({
  agents: null,
  selected: null,
  select: () => {},
});

/** Where the picked agent is remembered, per workspace. */
export function selectedAgentKey(organizationId: number | null | undefined): string {
  return `lightmove.nav.agent.${organizationId ?? "none"}`;
}

function readSelected(key: string): number | null {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    const id = raw ? Number(raw) : NaN;
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

function writeSelected(key: string, id: number) {
  try {
    globalThis.localStorage?.setItem(key, String(id));
  } catch {
    // Storage unavailable: the menu falls back to the primary agent.
  }
}

/** The agent callers reach: the one a number rings, else the first. */
export function primaryWorkspaceAgent(agents: readonly WorkspaceAgent[]): WorkspaceAgent | null {
  return agents.find((a) => a.phone_numbers.length > 0) ?? agents[0] ?? null;
}

export function WorkspaceAgentsProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, loading } = useAuth();
  const { orgContext } = useOrgConfig();
  const [agents, setAgents] = useState<readonly WorkspaceAgent[] | null>(null);
  const previousPath = useRef<string | null>(null);
  const [version, setVersion] = useState(0);
  const storageKey = selectedAgentKey(orgContext?.organization_id);
  const [picked, setPicked] = useState<number | null>(null);
  const agentShell = useAgentShellOptional();

  useEffect(() => {
    const before = previousPath.current;
    previousPath.current = pathname;
    if (before !== null && before !== pathname && before.startsWith("/workflow")) {
      setVersion((v) => v + 1);
    }
  }, [pathname]);

  const userId = user?.id;
  useEffect(() => {
    if (loading || !userId) return;
    let ignore = false;
    const load = async () => {
      try {
        const res = await getWorkflowsSummaryApiV1WorkflowSummaryGet({
          query: { status: "active", include_numbers: true },
        });
        if (!ignore && res.data) {
          setAgents(res.data.map(({ id, name, phone_numbers }) => ({ id, name, phone_numbers: phone_numbers ?? [] })));
        }
      } catch {
        // Keep what we had; the menu falls back to the agents list.
      }
    };
    void load();
    return () => {
      ignore = true;
    };
  }, [loading, userId, version]);

  // The remembered pick for this workspace.
  useEffect(() => {
    setPicked(readSelected(storageKey));
  }, [storageKey]);

  const select = useCallback(
    (agentId: number) => {
      setPicked(agentId);
      writeSelected(storageKey, agentId);
    },
    [storageKey],
  );

  // Being on an agent's screen selects that agent.
  const onAgent = agentIdFromPath(pathname);
  useEffect(() => {
    if (onAgent !== null && onAgent !== picked) select(onAgent);
  }, [onAgent, picked, select]);

  const shellAgentName = agentShell?.workflowId === onAgent ? agentShell?.agent?.name : undefined;
  const value = useMemo<WorkspaceAgentsValue>(() => {
    const wanted = onAgent ?? picked;
    let selected = agents
      ? (agents.find((a) => a.id === wanted) ?? (onAgent === null ? primaryWorkspaceAgent(agents) : null))
      : null;
    // An agent that isn't in the live list (archived, or just created): the
    // menu still stays on the agent whose screen is open.
    if (!selected && onAgent !== null && agents) {
      selected = { id: onAgent, name: shellAgentName ?? "This agent", phone_numbers: [] };
    }
    return { agents, selected, select };
  }, [agents, onAgent, picked, select, shellAgentName]);

  return <WorkspaceAgentsContext.Provider value={value}>{children}</WorkspaceAgentsContext.Provider>;
}

/** The workspace's agents, or null while unknown (also outside the provider). */
export function useWorkspaceAgents(): readonly WorkspaceAgent[] | null {
  return useContext(WorkspaceAgentsContext).agents;
}

/** The agent the menu's "Agent" section shows, and a way to pick another. */
export function useSelectedAgent(): WorkspaceAgentsValue {
  return useContext(WorkspaceAgentsContext);
}
