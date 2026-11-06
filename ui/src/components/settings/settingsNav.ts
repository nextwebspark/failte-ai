import {
  Bell,
  CircleDollarSign,
  Key,
  type LucideIcon,
  Mail,
  Plug,
  Settings,
  ShieldCheck,
  UserRound,
  Users,
} from "lucide-react";

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
};

export type SettingsNavSection = {
  label: string;
  items: SettingsNavItem[];
};

export const SETTINGS_SECTIONS: SettingsNavSection[] = [
  {
    label: "Workspace",
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
        title: "Billing",
        url: "/billing",
        icon: CircleDollarSign,
        description: "Balance, top-ups and invoices.",
        requires: "billing:read",
      },
    ],
  },
  {
    label: "Compliance",
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
