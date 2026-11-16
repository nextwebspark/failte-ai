import {
  AudioLines,
  Bell,
  CircleDollarSign,
  Cpu,
  Database,
  Key,
  LayoutDashboard,
  type LucideIcon,
  Mail,
  PhoneForwarded,
  Plug,
  Settings,
  ShieldCheck,
  UserRound,
  Users,
  Wrench,
} from "lucide-react";

import type { SettingScope } from "@/components/layout/ScopeNote";
import type { Permission } from "@/lib/auth/roles";

/**
 * Everything under Settings: one grouped menu (Workspace, Compliance,
 * Developer, Account) shared by the main nav's Settings row and the menu on
 * every settings screen. The screens keep their own routes, so existing links
 * (/team, /billing, /api-keys, /account) still work.
 */

export type SettingsNavItem = {
  title: string;
  url: string;
  icon: LucideIcon;
  /** The one line under the screen's title. */
  description: string;
  /** Hidden (and its route blocked) unless the caller's role grants this. */
  requires?: Permission;
  /**
   * A list with detail screens under it (/tools/<id>): only the list sits in
   * the settings frame; a detail screen keeps the full width.
   */
  listOnly?: boolean;
};

export type SettingsNavSection = {
  label: string;
  /** Who the section's settings reach, shown under each screen's title. */
  scope: SettingScope;
  items: SettingsNavItem[];
};

export const SETTINGS_SECTIONS: SettingsNavSection[] = [
  {
    label: "Workspace",
    scope: "workspace",
    items: [
      {
        title: "General",
        url: "/settings",
        icon: Settings,
        description: "Workspace name, defaults and how calls are reported.",
        requires: "org:manage",
      },
      {
        title: "Members",
        url: "/team",
        icon: Users,
        description: "Who can use this workspace, their roles and pending invitations.",
        requires: "members:read",
      },
      {
        title: "Notifications",
        url: "/settings/notifications",
        icon: Bell,
        description: "Who gets an email after calls, and texting callers their booking.",
        requires: "notifications:manage",
      },
      {
        title: "Reports by email",
        url: "/settings/reports",
        icon: Mail,
        description: "A daily, weekly or monthly summary of your calls, sent to your inbox.",
        requires: "reports:read",
      },
      {
        title: "Home layout",
        url: "/settings/home-layout",
        icon: LayoutDashboard,
        description: "Which cards everyone's Home starts with.",
        requires: "reports:schedule",
      },
      {
        title: "Billing",
        url: "/billing",
        icon: CircleDollarSign,
        description: "Balance, top-ups and invoices.",
        requires: "billing:read",
      },
    ],
  },
  {
    label: "Phone & AI setup",
    scope: "workspace",
    items: [
      {
        title: "Telephony",
        url: "/telephony-configurations",
        icon: PhoneForwarded,
        description: "The phone accounts and numbers your agents answer and call from.",
        requires: "telephony:read",
        listOnly: true,
      },
      {
        title: "Default voice & model",
        url: "/model-configurations",
        icon: Cpu,
        description: "How your agents listen, think and speak, unless an agent has its own.",
        requires: "credentials:write",
      },
      {
        title: "Prompt audio",
        url: "/recordings",
        icon: AudioLines,
        description: "Greetings and messages recorded in your own voice, for your agents to play on calls.",
        requires: "agents:write",
      },
      {
        title: "Tools",
        url: "/tools",
        icon: Wrench,
        description: "Things your agents can do during a call, like checking a booking system or passing the caller to a person.",
        requires: "agents:write",
        listOnly: true,
      },
      {
        title: "Files",
        url: "/files",
        icon: Database,
        description: "Documents your agents can look things up in, like a menu, price list or FAQs.",
        requires: "agents:write",
      },
    ],
  },
  {
    label: "Compliance",
    scope: "workspace",
    items: [
      {
        title: "Privacy & compliance",
        url: "/settings/compliance",
        icon: ShieldCheck,
        description:
          "How long call data is kept, what callers are told, and how to answer data requests.",
        requires: "calls:read",
      },
    ],
  },
  {
    label: "Developer",
    scope: "workspace",
    items: [
      {
        title: "API keys",
        url: "/api-keys",
        icon: Key,
        description: "Keys for the API and the details to call it.",
        requires: "api_keys:manage",
      },
      {
        title: "MCP & telemetry",
        url: "/settings/developer",
        icon: Plug,
        description: "The MCP server, Langfuse tracing and where call events are sent.",
        requires: "integrations:read",
      },
    ],
  },
  {
    label: "Account",
    scope: "you",
    items: [
      {
        title: "Your account",
        url: "/account",
        icon: UserRound,
        description: "Your profile, and exporting or deleting your data.",
      },
    ],
  },
];

const SETTINGS_ITEMS = SETTINGS_SECTIONS.flatMap((section) => section.items);

/** Route -> permission for every settings screen that needs one. */
export const SETTINGS_ROUTE_PERMISSIONS: Record<string, Permission> = Object.fromEntries(
  SETTINGS_ITEMS.filter(
    (item): item is SettingsNavItem & { requires: Permission } => Boolean(item.requires),
  )
    // General redirects members it isn't for to the first screen they can
    // use (see app/settings/page.tsx), so it is not blocked outright.
    .filter((item) => item.url !== "/settings")
    .map((item) => [item.url, item.requires]),
);

function matches(pathname: string, url: string): boolean {
  return pathname === url || pathname.startsWith(`${url}/`);
}

/** The settings screen `pathname` is on (longest match), or null. */
export function settingsItemFor(pathname: string): SettingsNavItem | null {
  let match: SettingsNavItem | null = null;
  for (const item of SETTINGS_ITEMS) {
    if (matches(pathname, item.url) && (!match || item.url.length > match.url.length)) {
      match = item;
    }
  }
  return match;
}

/** Who the settings on `pathname` reach, or null off the settings screens. */
export function settingsScopeFor(pathname: string): SettingScope | null {
  const item = settingsItemFor(pathname);
  if (!item) return null;
  return SETTINGS_SECTIONS.find((section) => section.items.includes(item))?.scope ?? null;
}

export function isSettingsRoute(pathname: string): boolean {
  return settingsItemFor(pathname) !== null;
}

/**
 * The settings sections this member may open. Until the role is known
 * (`can` is null) everything is listed rather than flashing a short menu.
 */
export function visibleSettingsSections(
  can: ((permission: Permission) => boolean) | null,
): SettingsNavSection[] {
  return SETTINGS_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !can || !item.requires || can(item.requires)),
  })).filter((section) => section.items.length > 0);
}

/** Where the main nav's Settings row leads: the first screen this member can open. */
export function firstSettingsUrl(can: ((permission: Permission) => boolean) | null): string {
  return visibleSettingsSections(can)[0]?.items[0]?.url ?? "/account";
}
