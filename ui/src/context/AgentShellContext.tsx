"use client";

import { usePathname } from "next/navigation";
import React, {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { WorkflowRuntimeNodeTransition } from "@/app/workflow/[workflowId]/components/workflow-tester/types";
import { getWorkflowApiV1WorkflowFetchWorkflowIdGet } from "@/client/sdk.gen";
import { agentIdFromPath } from "@/components/layout/agentNav";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";

/**
 * State the agent-level shell owns, shared by the three surfaces the canvas
 * keeps pinned while you move between sections (app-doc/claude-design/):
 * the header breadcrumb, the nav panel, and the test rail.
 *
 * The agent summary is fetched HERE — once, by the shell — because the nav and
 * the rail render outside any single section page and still need the agent's
 * name, status and id. Section pages keep loading their own detail as before.
 */

export type AgentSummary = {
  id: number;
  name: string;
  workflowUuid?: string;
  versionStatus?: string | null;
  totalRuns: number;
  templateContextVariables: Record<string, string>;
};

type RuntimeTransitionListener = (transition: WorkflowRuntimeNodeTransition) => void;

type AgentShellValue = {
  workflowId: number;
  agent: AgentSummary | null;
  loading: boolean;
  /** Keeps the nav/header in sync when a section renames the agent. */
  setAgentName: (name: string) => void;
  /** Lets the conversation section publish its version status to the shell. */
  setVersionStatus: (status: string | null) => void;

  // ---- test rail -------------------------------------------------------
  isRailOpen: boolean;
  setRailOpen: (open: boolean) => void;
  isSheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
  /** Opens the rail on desktop, the sheet below xl. */
  openTester: () => void;
  /**
   * Why testing is unavailable right now, or null. Owned by the conversation
   * section (unsaved changes, validation errors, viewing history) — every
   * other section leaves it null.
   */
  testerDisabledReason: string | null;
  setTesterDisabledReason: (reason: string | null) => void;
  /** The rail publishes runtime node transitions; the flow canvas listens. */
  emitRuntimeTransition: RuntimeTransitionListener;
  subscribeToRuntimeTransitions: (listener: RuntimeTransitionListener) => () => void;
};

const AgentShellContext = createContext<AgentShellValue | null>(null);

export function AgentShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const workflowId = agentIdFromPath(pathname);
  const { user } = useAuth();

  const [agent, setAgent] = useState<AgentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRailOpen, setRailOpen] = useState(true);
  const [isSheetOpen, setSheetOpen] = useState(false);
  const [testerDisabledReason, setTesterDisabledReason] = useState<string | null>(null);
  const listeners = useRef(new Set<RuntimeTransitionListener>());

  useEffect(() => {
    if (workflowId === null || !user) return;

    let ignore = false;
    setLoading(true);

    const fetchAgent = async () => {
      try {
        const response = await getWorkflowApiV1WorkflowFetchWorkflowIdGet({
          path: { workflow_id: workflowId },
        });
        const workflow = response.data;
        if (ignore || !workflow) return;
        setAgent({
          id: workflow.id,
          name: workflow.name,
          workflowUuid: workflow.workflow_uuid ?? undefined,
          versionStatus: workflow.version_status ?? null,
          totalRuns: workflow.total_runs ?? 0,
          templateContextVariables:
            (workflow.template_context_variables as Record<string, string>) ?? {},
        });
      } catch (error) {
        logger.error(`Error fetching agent for the editor shell: ${error}`);
      } finally {
        if (!ignore) setLoading(false);
      }
    };

    void fetchAgent();
    return () => {
      ignore = true;
    };
  }, [workflowId, user]);

  // A different agent means a different test session — never carry a rail
  // state (or a stale "unsaved changes" reason) across agents.
  useEffect(() => {
    setTesterDisabledReason(null);
  }, [workflowId]);

  const setAgentName = useCallback((name: string) => {
    setAgent((previous) => (previous ? { ...previous, name } : previous));
  }, []);

  const setVersionStatus = useCallback((versionStatus: string | null) => {
    setAgent((previous) => (previous ? { ...previous, versionStatus } : previous));
  }, []);

  const openTester = useCallback(() => {
    if (typeof window !== "undefined" && window.innerWidth >= 1280) {
      setRailOpen(true);
      return;
    }
    setSheetOpen(true);
  }, []);

  const emitRuntimeTransition = useCallback((transition: WorkflowRuntimeNodeTransition) => {
    listeners.current.forEach((listener) => listener(transition));
  }, []);

  const subscribeToRuntimeTransitions = useCallback(
    (listener: RuntimeTransitionListener) => {
      listeners.current.add(listener);
      return () => {
        listeners.current.delete(listener);
      };
    },
    [],
  );

  const value = useMemo<AgentShellValue | null>(() => {
    if (workflowId === null) return null;
    return {
      workflowId,
      agent,
      loading,
      setAgentName,
      setVersionStatus,
      isRailOpen,
      setRailOpen,
      isSheetOpen,
      setSheetOpen,
      openTester,
      testerDisabledReason,
      setTesterDisabledReason,
      emitRuntimeTransition,
      subscribeToRuntimeTransitions,
    };
  }, [
    workflowId,
    agent,
    loading,
    setAgentName,
    setVersionStatus,
    isRailOpen,
    isSheetOpen,
    openTester,
    testerDisabledReason,
    emitRuntimeTransition,
    subscribeToRuntimeTransitions,
  ]);

  return <AgentShellContext.Provider value={value}>{children}</AgentShellContext.Provider>;
}

/** Null outside an agent route — the workspace shell renders the same tree. */
export function useAgentShellOptional(): AgentShellValue | null {
  return useContext(AgentShellContext);
}

export function useAgentShell(): AgentShellValue {
  const value = useContext(AgentShellContext);
  if (!value) {
    throw new Error("useAgentShell must be used inside an agent route");
  }
  return value;
}
