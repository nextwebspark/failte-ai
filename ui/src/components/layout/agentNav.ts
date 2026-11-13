import {
  Bot,
  type LucideIcon,
  MessageSquare,
  Phone,
  Settings2,
  SlidersHorizontal,
  Smartphone,
} from "lucide-react";

import type { Permission } from "@/lib/auth/roles";

/**
 * An agent's own screens, all under `/workflow/<id>`.
 *
 * There is one menu (navConfig + AppSidebar): its "Agent" section shows the
 * selected agent (see workspaceAgents.tsx) and links to these screens for
 * that agent. Opening any `/workflow/<id>/...` screen selects agent <id>, so
 * the menu never points at a different agent than the page you are on.
 *
 * This file also names each screen for the header breadcrumb
 * (`agentSectionFor`), including the ones the menu reaches another way (an
 * agent's calls belong to the main Calls row).
 */

/** `/workflow/123`, `/workflow/123/settings`, … — every agent-level screen. */
const AGENT_ROUTE = /^\/workflow\/(\d+)(?:\/|$)/;

/** The workflow id when `pathname` is an agent-level screen, else null. */
export function agentIdFromPath(pathname: string): number | null {
  const match = AGENT_ROUTE.exec(pathname);
  return match ? Number(match[1]) : null;
}

export function isAgentRoute(pathname: string): boolean {
  return AGENT_ROUTE.test(pathname);
}

/** An agent's calls (`/workflow/1/runs`) or one call (`/workflow/1/run/9`). */
const AGENT_CALLS_ROUTE = /^\/workflow\/\d+\/(runs|run)(\/|$)/;

export function isAgentCallsRoute(pathname: string): boolean {
  return AGENT_CALLS_ROUTE.test(pathname);
}

export type AgentNavItem = {
  title: string;
  /** Appended to `/workflow/<id>` — "" is the conversation (the flow canvas). */
  segment: string;
  /** Appended to the link only (`#phone` scrolls to the phone channel). */
  hash?: string;
  icon: LucideIcon;
  /** Header strapline for the section. */
  subtitle: string;
  /** Extra sub-paths that belong to this section (detail routes). */
  altSegments?: string[];
  /** Hidden unless the member's role grants this (navConfig guards the route too). */
  requires?: Permission;
  /** Listed under the agent's collapsed "Advanced" row. */
  advanced?: boolean;
  /** Not a row of its own in the menu (reached from another row). */
  notInMenu?: boolean;
};

export const AGENT_PAGES: AgentNavItem[] = [
  {
    title: "What your agent knows",
    segment: "/facts",
    icon: Bot,
    subtitle: "Opening hours, address and answers your agent gives",
    requires: "agents:read",
  },
  {
    title: "Phone number",
    segment: "/deployment",
    hash: "#phone",
    icon: Smartphone,
    subtitle: "Put this agent on a phone number or your website",
  },
  {
    title: "Conversation",
    segment: "",
    icon: MessageSquare,
    subtitle: "The steps a call follows",
    requires: "agents:read",
    advanced: true,
  },
  {
    title: "Model and voice",
    segment: "/model",
    icon: SlidersHorizontal,
    subtitle: "The voice and language this agent uses",
    requires: "agents:write",
    advanced: true,
  },
  {
    title: "Advanced settings",
    segment: "/settings",
    icon: Settings2,
    subtitle: "Behaviour, variables, dictionary and diagnostics",
    requires: "agents:write",
    advanced: true,
  },
  {
    title: "Calls",
    segment: "/runs",
    icon: Phone,
    subtitle: "Every call this agent has taken",
    // A single call's detail page lives at /run/<id> — same section.
    altSegments: ["/run"],
    notInMenu: true,
  },
];

/** Absolute href for a nav item on a given agent. */
export function agentHref(workflowId: number, segment: string, hash = ""): string {
  return `/workflow/${workflowId}${segment}${hash}`;
}

/**
 * The agent screen a pathname belongs to. Longest matching segment wins, so
 * `/workflow/1/runs/9` still resolves to Calls and `/workflow/1` to Conversation.
 */
export function agentSectionFor(pathname: string): AgentNavItem | null {
  const workflowId = agentIdFromPath(pathname);
  if (workflowId === null) return null;

  const rest = pathname.slice(`/workflow/${workflowId}`.length);
  let match: AgentNavItem | null = null;
  let matchedLength = 0;

  for (const item of AGENT_PAGES) {
    if (item.segment === "") continue;
    for (const segment of [item.segment, ...(item.altSegments ?? [])]) {
      const isMatch = rest === segment || rest.startsWith(`${segment}/`);
      if (isMatch && segment.length > matchedLength) {
        match = item;
        matchedLength = segment.length;
      }
    }
  }

  // Everything that isn't a declared sub-section is the conversation itself.
  return match ?? AGENT_PAGES.find((item) => item.segment === "") ?? null;
}
