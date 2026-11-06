"use client";

import { usePathname } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";

import { getWorkflowsSummaryApiV1WorkflowSummaryGet } from "@/client/sdk.gen";
import { useAuth } from "@/lib/auth";

/**
 * The workspace's live (not archived) agents, for the shell's "Your agent"
 * links: with exactly one agent they go straight to it. Read once when the
 * shell mounts, and again after leaving an agent screen (where agents are
 * created, renamed and archived). Null while loading or when it can't be
 * read; the links then fall back to the agents list.
 */
export type WorkspaceAgent = { id: number; name: string };

const WorkspaceAgentsContext = createContext<readonly WorkspaceAgent[] | null>(null);

export function WorkspaceAgentsProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, loading } = useAuth();
  const [agents, setAgents] = useState<readonly WorkspaceAgent[] | null>(null);
  const previousPath = useRef<string | null>(null);
  const [version, setVersion] = useState(0);

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
        const res = await getWorkflowsSummaryApiV1WorkflowSummaryGet({ query: { status: "active" } });
        if (!ignore && res.data) setAgents(res.data.map(({ id, name }) => ({ id, name })));
      } catch {
        // Keep what we had; the links fall back to the agents list.
      }
    };
    void load();
    return () => {
      ignore = true;
    };
  }, [loading, userId, version]);

  return <WorkspaceAgentsContext.Provider value={agents}>{children}</WorkspaceAgentsContext.Provider>;
}

/** The workspace's agents, or null while unknown (also outside the provider). */
export function useWorkspaceAgents(): readonly WorkspaceAgent[] | null {
  return useContext(WorkspaceAgentsContext);
}
