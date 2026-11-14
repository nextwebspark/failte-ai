"use client";

import { usePathname } from "next/navigation";

import { useOpenFollowUpCount } from "@/components/dashboard/useDashboardData";
import { isSettingsRoute, visibleSettingsSections } from "@/components/settings/settingsNav";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useTelephonyConfigWarnings } from "@/context/TelephonyConfigWarningsContext";
import { useFeatureFlags } from "@/hooks/useFeatureFlags";
import type { Permission } from "@/lib/auth/roles";

import { agentHref, agentIdFromPath, agentSectionFor, isAgentCallsRoute, isAgentRoute } from "./agentNav";
import {
  CALLS_URL,
  FOLLOW_UPS_URL,
  getNavSections,
  isNavRowActive,
  isWithin,
  type NavItem,
  type NavSection,
} from "./navConfig";
import { useShellChrome } from "./shellContext";
import { useSelectedAgent } from "./workspaceAgents";

export type ResolvedNavItem = NavItem & {
  /** Where the row goes for this member and workspace. */
  href: string;
  isActive: boolean;
  showWarningDot: boolean;
};

export type ResolvedNavSection = Omit<NavSection, "items"> & { items: ResolvedNavItem[] };

/** Screens with a row of their own in the Workspace section, not under Settings. */
const OWN_ROW_SETTINGS = ["/team", "/billing"];

/**
 * Where the Settings row leads: the first settings screen this member may
 * open that doesn't already have its own row (Team, Billing).
 */
export function settingsHubUrl(can: ((permission: Permission) => boolean) | null): string {
  const items = visibleSettingsSections(can).flatMap((section) => section.items);
  return (items.find((item) => !OWN_ROW_SETTINGS.includes(item.url)) ?? items[0])?.url ?? "/account";
}

/**
 * The one menu as this member sees it: rows their role can't open and
 * switched-off areas left out, the Agent rows pointed at the selected agent,
 * and the lit row worked out. The sidebar, the phone tab bar and the More
 * sheet all read it, so they never disagree.
 *
 * The Agent sections are left out while the workspace has no agent; the
 * sidebar's switcher offers to create one instead.
 */
export function useWorkspaceNav(): ResolvedNavSection[] {
  const pathname = usePathname();
  const featureFlags = useFeatureFlags();
  const { returnTo } = useShellChrome();
  const { role, can } = useOrgConfig();
  const { agents, selected } = useSelectedAgent();
  const openFollowUps = useOpenFollowUpCount();
  const { telnyxMissingWebhookPublicKeyCount, vonageMissingSignatureSecretCount } = useTelephonyConfigWarnings();
  const hasTelephonyWarning = telnyxMissingWebhookPublicKeyCount > 0 || vonageMissingSignatureSecretCount > 0;

  // Until the role is known, show everything rather than flashing a short nav.
  const known = role !== null;
  const allowed = (item: NavItem) => !known || !item.requires || can(item.requires);
  const settingsUrl = settingsHubUrl(known ? can : null);

  // The agent screen open now, if any (a call's page is the Calls row's).
  const onAgentScreen = agentIdFromPath(pathname) !== null && !isAgentCallsRoute(pathname);
  const agentSegment = onAgentScreen ? agentSectionFor(pathname)?.segment : undefined;
  // An agent's calls, or one call opened from them (not from another list).
  const onAgentCalls = isAgentCallsRoute(pathname) && (!returnTo || isAgentRoute(returnTo));

  const resolve = (item: NavItem): ResolvedNavItem => {
    let href = item.url;
    let isActive: boolean;
    if (item.settingsHub) {
      href = settingsUrl;
      isActive = isSettingsRoute(pathname) && !OWN_ROW_SETTINGS.some((url) => isWithin(pathname, url));
    } else if (item.agentSegment !== undefined) {
      // While the agents load, the rows lead to the agents list.
      href = selected ? agentHref(selected.id, item.agentSegment, item.agentHash) : item.url;
      isActive = onAgentScreen && agentSegment === item.agentSegment;
    } else if (item.url === "/workflow") {
      // Voice agents: the list, creating one and folders; not an agent's screens.
      isActive = isWithin(pathname, item.url) && !isAgentRoute(pathname);
    } else {
      isActive =
        isNavRowActive(item.url, pathname, returnTo) || (item.url === CALLS_URL && onAgentCalls);
    }
    return {
      ...item,
      badge: item.url === FOLLOW_UPS_URL ? (openFollowUps ?? undefined) : item.badge,
      href,
      isActive,
      showWarningDot: Boolean(item.showsTelephonyWarning && hasTelephonyWarning),
    };
  };

  const noAgent = agents !== null && agents.length === 0 && selected === null;
  return getNavSections(featureFlags)
    .filter((section) => !(noAgent && (section.id === "agent" || section.id === "agent-advanced")))
    .map((section) => ({ ...section, items: section.items.filter(allowed).map(resolve) }))
    .filter((section) => section.items.length > 0);
}
