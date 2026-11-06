import {
  AudioLines,
  BookOpen,
  Cpu,
  Database,
  FileText,
  GitBranch,
  Home,
  type LucideIcon,
  Megaphone,
  Phone,
  Plug,
  Settings,
  TrendingUp,
  Wrench,
} from "lucide-react";

import { SETTINGS_ROUTE_PERMISSIONS } from "@/components/settings/settingsNav";
import { DEFAULT_FEATURE_FLAGS, type Feature, type FeatureFlags } from "@/config/features";
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
  /**
   * The Settings row: it leads to the first settings screen the member can
   * open and stays lit on all of them (components/settings/settingsNav.ts).
   */
  settingsHub?: boolean;
  /** Listed only while this product area is switched on (config/features.ts). */
  feature?: Feature;
};

export type NavSection = {
  label?: string;
  items: NavItem[];
};

/** Every workspace screen, switched-off areas included (route permissions). */
const ALL_NAV_SECTIONS: NavSection[] = [
  {
    items: [{ title: "Overview", url: "/overview", icon: Home }],
  },
  {
    label: "BUILD",
    items: [
      { title: "Voice agents", url: "/workflow", icon: GitBranch, requires: "agents:read" },
      { title: "Campaigns", url: "/campaigns", icon: Megaphone, requires: "campaigns:read", feature: "campaigns" },
      { title: "Models & voice", url: "/model-configurations", icon: Cpu, requires: "credentials:write" },
      {
        title: "Telephony",
        url: "/telephony-configurations",
        icon: Phone,
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
  {
    label: "MANAGE",
    items: [
      { title: "Calls", url: "/usage", icon: TrendingUp, requires: "reports:read" },
      { title: "Reports", url: "/reports", icon: FileText, requires: "reports:read" },
      // Team, Billing, Developers and Compliance live under Settings.
      { title: "Settings", url: "/settings", icon: Settings, settingsHub: true },
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
  "/overview": { title: "Overview", subtitle: "Everything running today" },
  "/workflow": { title: "Voice agents", subtitle: "The agents that answer your calls" },
  "/workflow/create": { title: "New voice agent", subtitle: "Pick a ready-made agent" },
  "/campaigns": { title: "Campaigns", subtitle: "Bulk runs across contact lists" },
  "/campaigns/new": { title: "New campaign", subtitle: "Pick an agent and a contact list" },
  "/model-configurations": { title: "Models & voice", subtitle: "Speech-to-speech or STT → LLM → TTS, voices" },
  "/telephony-configurations": { title: "Telephony", subtitle: "Providers, trunks and numbers" },
  "/tools": { title: "Tools", subtitle: "HTTP and MCP tools agents can call" },
  "/integrations": { title: "Integrations", subtitle: "Connect apps like Google Calendar to your agents" },
  "/skills": { title: "Skills", subtitle: "Playbooks your agents load when a caller needs them" },
  "/skills/new": { title: "New skill", subtitle: "Write a playbook your agents can load on demand" },
  "/skills/library": { title: "Skill library", subtitle: "Platform skills shared with every workspace" },
  "/files": { title: "Files", subtitle: "Documents agents can reference" },
  "/recordings": { title: "Prompt audio", subtitle: "Recorded greetings and messages your agents can play" },
  "/usage": { title: "Calls", subtitle: "Every call your agents answered or made" },
  "/reports": { title: "Reports", subtitle: "Daily call outcomes" },
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
      .filter((item): item is NavItem & { requires: Permission } => Boolean(item.requires))
      .map((item) => [item.url, item.requires]),
  ),
  ...SETTINGS_ROUTE_PERMISSIONS,
  "/workflow/create": "agents:write",
  "/campaigns/new": "campaigns:write",
  "/skills/new": "agents:write",
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
