import {
  AudioLines,
  BookOpen,
  Bot,
  CalendarDays,
  ChartLine,
  Cpu,
  Database,
  GitBranch,
  Home,
  ListChecks,
  type LucideIcon,
  Megaphone,
  Phone,
  PhoneForwarded,
  Plug,
  Settings,
  Smartphone,
  Wrench,
} from "lucide-react";

import { SETTINGS_ROUTE_PERMISSIONS } from "@/components/settings/settingsNav";
import { DEFAULT_FEATURE_FLAGS, type Feature, type FeatureFlags } from "@/config/features";
import type { Permission } from "@/lib/auth/roles";

/**
 * Single source of truth for the workspace ("org level") shell: what the left
 * nav lists, and what the top bar prints in the breadcrumb for each route.
 *
 * The layout follows the 5 November redesign (Home mock): the screens an
 * owner uses every day first, then "Your agent", then every builder screen
 * folded under one collapsed "Advanced setup" row.
 */

/**
 * A "Your agent" row whose address depends on the workspace's agents: with
 * exactly one agent it goes straight to that agent (see `agentRowHref`).
 */
export type AgentRowKind = "facts" | "phone";

export type NavItem = {
  title: string;
  url: string;
  icon: LucideIcon;
  /** Flags the amber dot the canvas puts on a nav row needing attention. */
  showsTelephonyWarning?: boolean;
  /** Hidden (and its route blocked) unless the caller's role grants this. */
  requires?: Permission;
  /**
   * The Settings row: it leads to the first settings screen the member can
   * open and stays lit on all of them (components/settings/settingsNav.ts).
   */
  settingsHub?: boolean;
  /** Listed only while this product area is switched on (config/features.ts). */
  feature?: Feature;
  /**
   * A count shown at the end of the row (e.g. open follow-ups). Nothing is
   * shown when it is unset or 0.
   */
  badge?: number;
  /** `url` is only the fallback: the real address comes from `agentRowHref`. */
  agentRow?: AgentRowKind;
};

export type NavSection = {
  /** Stable key (also the remembered open/closed state of a collapsible group). */
  id: "main" | "agent" | "advanced";
  label?: string;
  items: NavItem[];
  /** Shown as one row that opens and closes ("Advanced setup"). */
  collapsible?: boolean;
};

/** The Follow-ups row; its open count is set as `badge` by the sidebar. */
export const FOLLOW_UPS_URL = "/follow-ups";

/** Every workspace screen, switched-off areas included (route permissions). */
const ALL_NAV_SECTIONS: NavSection[] = [
  {
    id: "main",
    items: [
      { title: "Home", url: "/overview", icon: Home },
      { title: "Calls", url: "/usage", icon: Phone, requires: "reports:read" },
      { title: "Follow-ups", url: FOLLOW_UPS_URL, icon: ListChecks, requires: "calls:read" },
      { title: "Bookings", url: "/bookings", icon: CalendarDays, requires: "calls:read" },
      { title: "Reports", url: "/reports", icon: ChartLine, requires: "reports:read" },
    ],
  },
  {
    id: "agent",
    label: "Your agent",
    items: [
      { title: "What your agent knows", url: "/workflow", icon: Bot, agentRow: "facts", requires: "agents:read" },
      { title: "Phone number", url: "/telephony-configurations", icon: Smartphone, agentRow: "phone" },
      // Team, Billing, Developers and Compliance live under Settings.
      { title: "Settings", url: "/settings", icon: Settings, settingsHub: true },
    ],
  },
  {
    id: "advanced",
    label: "Advanced setup",
    collapsible: true,
    items: [
      { title: "Voice agents", url: "/workflow", icon: GitBranch, requires: "agents:read" },
      { title: "Campaigns", url: "/campaigns", icon: Megaphone, requires: "campaigns:read", feature: "campaigns" },
      { title: "Models & voice", url: "/model-configurations", icon: Cpu, requires: "credentials:write" },
      {
        title: "Telephony",
        url: "/telephony-configurations",
        icon: PhoneForwarded,
        showsTelephonyWarning: true,
        requires: "telephony:read",
      },
      { title: "Tools", url: "/tools", icon: Wrench, requires: "agents:write" },
      { title: "Integrations", url: "/integrations", icon: Plug, requires: "integrations:read" },
      { title: "Skills", url: "/skills", icon: BookOpen, requires: "agents:read", feature: "skills" },
      { title: "Files", url: "/files", icon: Database, requires: "agents:write" },
      { title: "Prompt audio", url: "/recordings", icon: AudioLines, requires: "agents:write" },
    ],
  },
];

/** The workspace's agents as the "Your agent" rows need them; null while loading. */
export type WorkspaceAgents = readonly { id: number }[] | null;

/**
 * Where a "Your agent" row goes. "Your agent" is singular, but a workspace
 * may have none or several:
 *   - What your agent knows: the one agent's facts; with none, create one
 *     (or the agents list for someone who can't); with several, the list.
 *   - Phone number: the one agent's number; otherwise the phone accounts for
 *     someone who may open them, else the agents list.
 */
export function agentRowHref(
  kind: AgentRowKind,
  agents: WorkspaceAgents,
  can: ((permission: Permission) => boolean) | null,
): string {
  const only = agents?.length === 1 ? agents[0] : null;
  if (kind === "facts") {
    if (only) return `/workflow/${only.id}/facts`;
    if (agents?.length === 0 && (!can || can("agents:write"))) return "/workflow/create";
    return "/workflow";
  }
  if (only) return `/workflow/${only.id}/deployment#phone`;
  if (!can || can("telephony:read")) return "/telephony-configurations";
  return "/workflow";
}

/** What the left nav lists: areas that are switched off are left out. */
export function getNavSections(flags: FeatureFlags): NavSection[] {
  return ALL_NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.feature || flags[item.feature]),
  }));
}

/** `/tools/abc` is within `/tools`; `/toolsets` would not be. */
export function isWithin(pathname: string, url: string): boolean {
  return pathname === url || pathname.startsWith(`${url}/`);
}

/**
 * Whether a workspace nav row is lit: the screen or anything under it
 * (`/telephony-configurations/7`, `/skills/library/3`). A run opened from a
 * workspace list (`?from=/usage?page=2`) keeps that list's row lit.
 */
export function isNavRowActive(url: string, pathname: string, returnTo?: string | null): boolean {
  if (isWithin(pathname, url)) return true;
  return Boolean(returnTo && isWithin(returnTo.split("?")[0], url));
}

/** The left nav with the default switches (before the runtime ones are read). */
export const NAV_SECTIONS: NavSection[] = getNavSections(DEFAULT_FEATURE_FLAGS);

export type PageMeta = {
  title: string;
  subtitle?: string;
};

/**
 * Route prefix -> breadcrumb copy. Matched longest-prefix-first, so a detail
 * route (/campaigns/12) inherits its section's title until it declares its own.
 */
const PAGE_META: Record<string, PageMeta> = {
  "/overview": { title: "Home", subtitle: "How your phone agent is doing" },
  "/workflow": { title: "Voice agents", subtitle: "The agents that answer your calls" },
  "/workflow/create": { title: "New voice agent", subtitle: "Pick a ready-made agent" },
  "/campaigns": { title: "Campaigns", subtitle: "Bulk runs across contact lists" },
  "/campaigns/new": { title: "New campaign", subtitle: "Pick an agent and a contact list" },
  "/model-configurations": { title: "Models & voice", subtitle: "How your agents listen, think and speak" },
  "/telephony-configurations": { title: "Telephony", subtitle: "Your phone accounts and numbers" },
  "/tools": { title: "Tools", subtitle: "Things your agents can do during a call" },
  "/integrations": { title: "Integrations", subtitle: "Connect apps like Google Calendar to your agents" },
  "/skills": { title: "Skills", subtitle: "Playbooks your agents load when a caller needs them" },
  "/skills/new": { title: "New skill", subtitle: "Write a playbook your agents can load on demand" },
  "/skills/library": { title: "Skill library", subtitle: "Platform skills shared with every workspace" },
  "/files": { title: "Files", subtitle: "Documents your agents can look things up in" },
  "/recordings": { title: "Prompt audio", subtitle: "Recorded greetings and messages your agents can play" },
  "/usage": { title: "Calls", subtitle: "Every call your agents answered or made" },
  "/follow-ups": { title: "Follow-ups", subtitle: "Calls that need a person" },
  "/bookings": { title: "Bookings", subtitle: "Tables and appointments your agent booked" },
  "/reports": { title: "Reports", subtitle: "Your business in numbers" },
  // Settings screens print their own title and description (SettingsShell),
  // so the header only names the area.
  "/settings": { title: "Settings" },
  "/team": { title: "Settings" },
  "/billing": { title: "Settings" },
  "/api-keys": { title: "Settings" },
  "/account": { title: "Settings" },
  "/automation": { title: "Automation", subtitle: "Scheduled and triggered runs" },
  "/superadmin": { title: "Platform admin", subtitle: "Every workspace: switches, billing, users and health" },
  "/impersonate": { title: "Impersonate", subtitle: "Act as another user" },
};

/** Longest matching prefix wins; falls back to the workspace name. */
export function getPageMeta(pathname: string): PageMeta {
  let match: PageMeta | null = null;
  let matchedLength = 0;

  for (const [prefix, meta] of Object.entries(PAGE_META)) {
    const isMatch = pathname === prefix || pathname.startsWith(`${prefix}/`);
    if (isMatch && prefix.length > matchedLength) {
      match = meta;
      matchedLength = prefix.length;
    }
  }

  return match ?? { title: "Workspace" };
}

/**
 * Route prefix -> permission needed to use the screen. Covers every nav item
 * plus screens that only make sense for editors. Longest prefix wins; routes
 * not listed here are open to every member.
 */
const ROUTE_PERMISSIONS: Record<string, Permission> = {
  ...Object.fromEntries(
    ALL_NAV_SECTIONS.flatMap((section) => section.items)
      // A "Your agent" row's url is only a fallback address, not its screen.
      .filter((item): item is NavItem & { requires: Permission } => Boolean(item.requires) && !item.agentRow)
      .map((item) => [item.url, item.requires]),
  ),
  ...SETTINGS_ROUTE_PERMISSIONS,
  "/workflow/create": "agents:write",
  "/campaigns/new": "campaigns:write",
  "/skills/new": "agents:write",
  "/automation": "agents:write",
  // Every member sees and ticks off follow-ups (the menu row may also say so).
  "/follow-ups": "calls:read",
};

export function getRequiredPermission(pathname: string): Permission | null {
  let match: Permission | null = null;
  let matchedLength = 0;
  for (const [prefix, permission] of Object.entries(ROUTE_PERMISSIONS)) {
    const isMatch = pathname === prefix || pathname.startsWith(`${prefix}/`);
    if (isMatch && prefix.length > matchedLength) {
      match = permission;
      matchedLength = prefix.length;
    }
  }
  return match;
}
