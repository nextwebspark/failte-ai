"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  getWorkflowApiV1WorkflowFetchWorkflowIdGet,
  getWorkflowsApiV1WorkflowFetchGet,
} from "@/client/sdk.gen";
import { StatusPill } from "@/components/ui/status-pill";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import {
  resolveWorkflowConfigurations,
  type WorkflowConfigurations,
} from "@/types/workflow-configurations";

/** Agents read one by one; a workspace with more is pointed at the agent list. */
export const MAX_AGENTS_CHECKED = 50;

export type AgentDisclosure = {
  id: number;
  name: string;
  enabled: boolean;
  type: "text" | "audio";
};

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; agents: AgentDisclosure[]; unchecked: number };

/**
 * Whether each active agent plays the AI and recording notice at the start of
 * a call. Read from each agent's saved settings with the same resolver the
 * agent's Advanced settings screen uses, so the two never disagree.
 */
export function AgentDisclosureList() {
  const { user, loading: authLoading } = useAuth();
  const hasFetched = useRef(false);
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;
    void load();
  }, [authLoading, user]);

  async function load() {
    const list = await getWorkflowsApiV1WorkflowFetchGet({ query: { status: "active" } });
    if (list.error || !list.data) {
      setState({ status: "error", message: detailFromError(list.error, "Could not load your agents") });
      return;
    }
    const active = list.data.slice(0, MAX_AGENTS_CHECKED);
    const details = await Promise.all(
      active.map((agent) =>
        getWorkflowApiV1WorkflowFetchWorkflowIdGet({ path: { workflow_id: agent.id } }),
      ),
    );
    if (details.some((detail) => detail.error || !detail.data)) {
      setState({ status: "error", message: "Could not read every agent's settings. Reload to try again." });
      return;
    }
    const agents = details.map((detail) => {
      const data = detail.data!;
      const { call_disclosure } = resolveWorkflowConfigurations(
        data.workflow_configurations as Partial<WorkflowConfigurations> | null,
      );
      return { id: data.id, name: data.name, enabled: call_disclosure.enabled, type: call_disclosure.type };
    });
    setState({ status: "ready", agents, unchecked: list.data.length - active.length });
  }

  if (state.status === "loading") {
    return <p className="px-[18px] py-3.5 text-sm text-muted-foreground">Checking your agents…</p>;
  }
  if (state.status === "error") {
    return (
      <p role="alert" className="px-[18px] py-3.5 text-sm text-destructive">
        {state.message}
      </p>
    );
  }
  if (state.agents.length === 0) {
    return (
      <p className="px-[18px] py-3.5 text-sm text-ink-2">
        No active agents yet. New agents play the notice unless you turn it off.
      </p>
    );
  }

  const off = state.agents.filter((agent) => !agent.enabled).length;

  return (
    <div>
      <p className="px-[18px] pt-3.5 text-caption text-ink-2">
        {off === 0
          ? `All ${state.agents.length} active agent${state.agents.length === 1 ? "" : "s"} play the notice.`
          : `${off} of ${state.agents.length} active agents do not play the notice. Turn it back on unless callers are told another way.`}
      </p>
      <ul className="divide-y divide-line-soft">
        {state.agents.map((agent) => (
          <li key={agent.id} className="flex items-center gap-3 px-[18px] py-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-caption font-semibold text-foreground">{agent.name}</p>
              <p className="text-xs text-ink-3">
                {agent.enabled
                  ? agent.type === "audio"
                    ? "Plays a recorded notice"
                    : "Speaks the notice in the agent's voice"
                  : "No notice at the start of calls"}
              </p>
            </div>
            <StatusPill tone={agent.enabled ? "ok" : "warn"} dot>
              {agent.enabled ? "On" : "Off"}
            </StatusPill>
            <Link
              href={`/workflow/${agent.id}/settings#call`}
              aria-label={`Edit notice for ${agent.name}`}
              className="shrink-0 text-caption font-medium text-brand hover:underline"
            >
              Edit
            </Link>
          </li>
        ))}
      </ul>
      {state.unchecked > 0 && (
        <p className="px-[18px] pb-3.5 text-xs text-ink-3">
          {state.unchecked} more active agent{state.unchecked === 1 ? " is" : "s are"} not checked here. Open
          each one&apos;s Advanced settings to check it.
        </p>
      )}
      <p className="border-t border-line-soft px-[18px] py-3 text-xs text-ink-3">
        Shown as saved in each agent&apos;s settings. A change takes effect on calls once the agent is published.
      </p>
    </div>
  );
}
