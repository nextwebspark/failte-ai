import {
  AudioLines,
  CircleDollarSign,
  Cpu,
  Database,
  FileText,
  GitBranch,
  Home,
  Key,
  type LucideIcon,
  Megaphone,
  Phone,
  Plug,
  Settings,
  TrendingUp,
  Users,
  Wrench,
} from "lucide-react";

import type { Permission } from "@/lib/auth/roles";

/**
 * Single source of truth for the workspace ("org level") shell: what the left
 * nav lists, and what the top bar prints in the breadcrumb for each route.
 *
 * The design canvas (app-doc/claude-design/Failte AI v2.dc.html) carries the
 * page name and its one-line strapline in the HEADER, not in the page body —
 * `title` / `subtitle` below are the same strings the canvas uses, so the
 * screens themselves no longer repeat them.
 */

export type NavItem = {
  title: string;
  url: string;
  icon: LucideIcon;
  /** Flags the amber dot the canvas puts on a nav row needing attention. */
  showsTelephonyWarning?: boolean;
  /** Hidden (and its route blocked) unless the caller's role grants this. */
  requires?: Permission;
};

export type NavSection = {
  label?: string;
  items: NavItem[];
};

export const NAV_SECTIONS: NavSection[] = [
  {
    items: [{ title: "Overview", url: "/overview", icon: Home }],
  },
  {
    label: "BUILD",
    items: [
      { title: "Voice agents", url: "/workflow", icon: GitBranch, requires: "agents:read" },
      { title: "Campaigns", url: "/campaigns", icon: Megaphone, requires: "campaigns:read" },
      { title: "Models", url: "/model-configurations", icon: Cpu, requires: "credentials:write" },
      {
        title: "Telephony",
        url: "/telephony-configurations",
        icon: Phone,
        showsTelephonyWarning: true,
        requires: "telephony:read",
      },
      { title: "Tools", url: "/tools", icon: Wrench, requires: "agents:write" },
      { title: "Integrations", url: "/integrations", icon: Plug, requires: "integrations:read" },
      { title: "Files", url: "/files", icon: Database, requires: "agents:write" },
      { title: "Recordings", url: "/recordings", icon: AudioLines, requires: "agents:write" },
      { title: "Developers", url: "/api-keys", icon: Key, requires: "api_keys:manage" },
    ],
  },
  {
    label: "MANAGE",
    items: [
      { title: "Agent runs", url: "/usage", icon: TrendingUp, requires: "reports:read" },
      { title: "Billing", url: "/billing", icon: CircleDollarSign, requires: "billing:read" },
      { title: "Reports", url: "/reports", icon: FileText, requires: "reports:read" },
      { title: "Team", url: "/team", icon: Users, requires: "members:read" },
      { title: "Workspace settings", url: "/settings", icon: Settings, requires: "integrations:read" },
    ],
  },
];

export type PageMeta = {
  title: string;
  subtitle?: string;
};

/**
 * Route prefix -> breadcrumb copy. Matched longest-prefix-first, so a detail
 * route (/campaigns/12) inherits its section's title until it declares its own.
 */
const PAGE_META: Record<string, PageMeta> = {
  "/overview": { title: "Overview", subtitle: "Everything running today" },
  "/workflow": { title: "Voice agents", subtitle: "Build and manage call flows" },
  "/workflow/create": { title: "New voice agent", subtitle: "Start from a template or a blank flow" },
  "/campaigns": { title: "Campaigns", subtitle: "Bulk runs across contact lists" },
  "/campaigns/new": { title: "New campaign", subtitle: "Pick an agent and a contact list" },
  "/model-configurations": { title: "Models", subtitle: "LLM, speech and transcription stacks" },
  "/telephony-configurations": { title: "Telephony", subtitle: "Providers, trunks and numbers" },
  "/tools": { title: "Tools", subtitle: "HTTP and MCP tools agents can call" },
  "/integrations": { title: "Integrations", subtitle: "Connect apps like Google Calendar to your agents" },
  "/files": { title: "Files", subtitle: "Documents agents can reference" },
  "/recordings": { title: "Recordings", subtitle: "Shared audio for prompts and transitions" },
  "/api-keys": { title: "Developers", subtitle: "API keys and integration details" },
  "/usage": { title: "Agent runs", subtitle: "Call history across every agent" },
  "/billing": { title: "Billing", subtitle: "Balance, top-ups and invoices" },
  "/reports": { title: "Reports", subtitle: "Daily call outcomes" },
  "/settings": { title: "Workspace settings", subtitle: "Platform configuration and integrations" },
  "/team": { title: "Team", subtitle: "Members, roles and invitations" },
  "/automation": { title: "Automation", subtitle: "Scheduled and triggered runs" },
  "/superadmin": { title: "Superadmin", subtitle: "Cross-organisation administration" },
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
    NAV_SECTIONS.flatMap((section) => section.items)
      .filter((item): item is NavItem & { requires: Permission } => Boolean(item.requires))
      .map((item) => [item.url, item.requires]),
  ),
  "/workflow/create": "agents:write",
  "/campaigns/new": "campaigns:write",
  "/automation": "agents:write",
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
