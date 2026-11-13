import {
  AudioLines,
  BookOpen,
  CalendarDays,
  ChartLine,
  CircleDollarSign,
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
  Users,
  Wrench,
} from "lucide-react";

import { SETTINGS_ROUTE_PERMISSIONS } from "@/components/settings/settingsNav";
import { DEFAULT_FEATURE_FLAGS, type Feature, type FeatureFlags } from "@/config/features";
import type { Permission } from "@/lib/auth/roles";

import { AGENT_PAGES } from "./agentNav";

/**
 * Single source of truth for the shell's ONE menu: what the left nav lists
 * (on every screen, agent screens included), and what the top bar prints in
 * the breadcrumb for each route.
 *
 *   Home · Calls · Follow-ups · Bookings · Reports        the business, every day
 *   AGENT   [switcher: which agent, which number rings it]
 *           What your agent knows · Phone number
 *           Advanced ›  Conversation · Model and voice · Advanced settings
 *   WORKSPACE  Voice agents · Team · Billing · Settings
 *           Advanced setup ›  Integrations · Tools · Files · Telephony ·
 *                             Models & voice · Prompt audio (· Campaigns · Skills)
 *
 * The Agent rows always point at the selected agent (workspaceAgents.tsx).
 */

export type NavItem = {
  title: string;
  /** For an Agent row: only the fallback while no agent is known. */
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
  /** An Agent row: the screen under `/workflow/<selected id>`. */
  agentSegment?: string;
  /** Appended to an Agent row's link (`#phone`). */
  agentHash?: string;
};

export type NavSection = {
  /** Stable key (also the remembered open/closed state of a collapsible group). */
  id: "main" | "agent" | "agent-advanced" | "workspace" | "advanced";
  label?: string;
  items: NavItem[];
  /** Shown as one row that opens and closes ("Advanced"). */
  collapsible?: boolean;
};

/** The Follow-ups row; its open count is set as `badge` by the sidebar. */
export const FOLLOW_UPS_URL = "/follow-ups";

/** The Calls row: also lit on an agent's own calls and on one call. */
export const CALLS_URL = "/usage";

const agentRows = (advanced: boolean): NavItem[] =>
  AGENT_PAGES.filter((page) => !page.notInMenu && Boolean(page.advanced) === advanced).map((page) => ({
    title: page.title,
    url: "/workflow",
    icon: page.icon,
    requires: page.requires,
    agentSegment: page.segment,
    agentHash: page.hash,
  }));

/** Every screen in the menu, switched-off areas included (route permissions). */
const ALL_NAV_SECTIONS: NavSection[] = [
  {
    id: "main",
    items: [
      { title: "Home", url: "/overview", icon: Home },
      { title: "Calls", url: CALLS_URL, icon: Phone, requires: "reports:read" },
      { title: "Follow-ups", url: FOLLOW_UPS_URL, icon: ListChecks, requires: "calls:read" },
      { title: "Bookings", url: "/bookings", icon: CalendarDays, requires: "calls:read" },
      { title: "Reports", url: "/reports", icon: ChartLine, requires: "reports:read" },
    ],
  },
  { id: "agent", label: "Agent", items: agentRows(false) },
  { id: "agent-advanced", label: "Advanced", collapsible: true, items: agentRows(true) },
  {
    id: "workspace",
    label: "Workspace",
    items: [
      { title: "Voice agents", url: "/workflow", icon: GitBranch, requires: "agents:read" },
      { title: "Team", url: "/team", icon: Users, requires: "members:read" },
      { title: "Billing", url: "/billing", icon: CircleDollarSign, requires: "billing:read" },
      // Notifications, Reports by email, Compliance, API keys and Your account
      // live under Settings.
      { title: "Settings", url: "/settings", icon: Settings, settingsHub: true },
    ],
  },
  {
    id: "advanced",
    label: "Advanced setup",
    collapsible: true,
    items: [
      { title: "Integrations", url: "/integrations", icon: Plug, requires: "integrations:read" },
      { title: "Tools", url: "/tools", icon: Wrench, requires: "agents:write" },
      { title: "Files", url: "/files", icon: Database, requires: "agents:write" },
      {
        title: "Telephony",
        url: "/telephony-configurations",
        icon: PhoneForwarded,
        showsTelephonyWarning: true,
        requires: "telephony:read",
      },
      { title: "Models & voice", url: "/model-configurations", icon: Cpu, requires: "credentials:write" },
      { title: "Prompt audio", url: "/recordings", icon: AudioLines, requires: "agents:write" },
      { title: "Campaigns", url: "/campaigns", icon: Megaphone, requires: "campaigns:read", feature: "campaigns" },
      { title: "Skills", url: "/skills", icon: BookOpen, requires: "agents:read", feature: "skills" },
    ],
  },
];

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
      // An Agent row's url is only a fallback address, not its screen.
      .filter(
        (item): item is NavItem & { requires: Permission } => Boolean(item.requires) && item.agentSegment === undefined,
      )
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

/**
 * An agent's editing screens (Advanced settings, Model and voice): only for
 * people who may change the agent. Staff still see the agent's calls,
 * what it knows, its phone number and its conversation.
 */
const AGENT_EDIT_SCREEN = /^\/workflow\/\d+\/(settings|model)(\/|$)/;

export function getRequiredPermission(pathname: string): Permission | null {
  if (AGENT_EDIT_SCREEN.test(pathname)) return "agents:write";
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
