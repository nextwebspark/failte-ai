import {
  type LucideIcon,
  MessageSquare,
  Settings2,
  SlidersHorizontal,
  TrendingUp,
  Zap,
} from "lucide-react";

/**
 * The agent ("editor level") navigation, mirroring the design canvas
 * (app-doc/claude-design/Failte AI v2.dc.html).
 *
 * The canvas swaps the whole nav panel when you open an agent: a "back to the
 * workspace" row and the agent's identity sit on top, then grouped sections
 * that only ever change the CENTRE panel — the header, the nav and the test
 * rail stay put. These are the same groups the canvas uses (Configure /
 * Connect / Analyse), narrowed to the sections this app actually has.
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

export type AgentNavItem = {
  title: string;
  /** Appended to `/workflow/<id>` — "" is the conversation (the flow canvas). */
  segment: string;
  icon: LucideIcon;
  /** Header strapline for the section, the canvas's `subtitle`. */
  subtitle: string;
  /** Extra sub-paths that belong to this section (detail routes). */
  altSegments?: string[];
};

export type AgentNavSection = {
  label?: string;
  items: AgentNavItem[];
};

export const AGENT_NAV_SECTIONS: AgentNavSection[] = [
  {
    label: "CONFIGURE",
    items: [
      {
        title: "Conversation",
        segment: "",
        icon: MessageSquare,
        subtitle: "The call flow this agent follows",
      },
      {
        title: "Model and voice",
        segment: "/model",
        icon: SlidersHorizontal,
        subtitle: "Per-agent LLM, speech and transcription overrides",
      },
      {
        title: "Advanced settings",
        segment: "/settings",
        icon: Settings2,
        subtitle: "Behaviour, variables, dictionary and diagnostics",
      },
    ],
  },
  {
    label: "CONNECT",
    items: [
      {
        title: "Deployment",
        segment: "/deployment",
        icon: Zap,
        subtitle: "Put this agent on your website",
      },
    ],
  },
  {
    label: "ANALYSE",
    items: [
      {
        title: "Runs",
        segment: "/runs",
        icon: TrendingUp,
        subtitle: "Every call this agent has taken",
        // A single run's detail page lives at /run/<id> — same section.
        altSegments: ["/run"],
      },
    ],
  },
];

const AGENT_NAV_ITEMS = AGENT_NAV_SECTIONS.flatMap((section) => section.items);

/** Absolute href for a nav item on a given agent. */
export function agentHref(workflowId: number, segment: string): string {
  return `/workflow/${workflowId}${segment}`;
}

/**
 * The nav item a pathname belongs to. Longest matching segment wins, so
 * `/workflow/1/runs/9` still resolves to Runs and `/workflow/1` to Conversation.
 */
export function agentSectionFor(pathname: string): AgentNavItem | null {
  const workflowId = agentIdFromPath(pathname);
  if (workflowId === null) return null;

  const rest = pathname.slice(`/workflow/${workflowId}`.length);
  let match: AgentNavItem | null = null;

  for (const item of AGENT_NAV_ITEMS) {
    if (item.segment === "") continue;
    for (const segment of [item.segment, ...(item.altSegments ?? [])]) {
      const isMatch = rest === segment || rest.startsWith(`${segment}/`);
      if (isMatch && segment.length > (match?.segment.length ?? 0)) {
        match = item;
      }
    }
  }

  // Everything that isn't a declared sub-section is the conversation itself.
  return match ?? AGENT_NAV_ITEMS.find((item) => item.segment === "") ?? null;
}
