"use client";

import { usePathname } from "next/navigation";

import { useOpenFollowUpCount } from "@/components/dashboard/useDashboardData";
import { firstSettingsUrl, isSettingsRoute } from "@/components/settings/settingsNav";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useTelephonyConfigWarnings } from "@/context/TelephonyConfigWarningsContext";
import { useFeatureFlags } from "@/hooks/useFeatureFlags";

import { isWorkspaceAgentScreen } from "./agentNav";
import {
  agentRowHref,
  FOLLOW_UPS_URL,
  getNavSections,
  isNavRowActive,
  isWithin,
  type NavItem,
  type NavSection,
} from "./navConfig";
import { useShellChrome } from "./shellContext";
import { useWorkspaceAgents } from "./workspaceAgents";

export type ResolvedNavItem = NavItem & {
  /** Where the row goes for this member and workspace. */
  href: string;
  isActive: boolean;
  showWarningDot: boolean;
};

export type ResolvedNavSection = Omit<NavSection, "items"> & { items: ResolvedNavItem[] };

/**
 * The workspace nav as this member sees it: rows their role can't open and
 * switched-off areas left out, "Your agent" rows pointed at the agent, and
 * the lit row worked out. The sidebar, the phone tab bar and the More sheet
 * all read it, so they never disagree.
 */
export function useWorkspaceNav(): ResolvedNavSection[] {
  const pathname = usePathname();
  const featureFlags = useFeatureFlags();
  const { returnTo } = useShellChrome();
  const { role, can } = useOrgConfig();
  const agents = useWorkspaceAgents();
  const openFollowUps = useOpenFollowUpCount();
  const { telnyxMissingWebhookPublicKeyCount, vonageMissingSignatureSecretCount } = useTelephonyConfigWarnings();
  const hasTelephonyWarning = telnyxMissingWebhookPublicKeyCount > 0 || vonageMissingSignatureSecretCount > 0;

  // Until the role is known, show everything rather than flashing a short nav.
  const known = role !== null;
  const allowed = (item: NavItem) => !known || !item.requires || can(item.requires);
  const settingsUrl = firstSettingsUrl(known ? can : null);

  const resolve = (item: NavItem): ResolvedNavItem => {
    let href = item.url;
    let isActive: boolean;
    if (item.settingsHub) {
      href = settingsUrl;
      isActive = isSettingsRoute(pathname);
    } else if (item.agentRow) {
      href = agentRowHref(item.agentRow, agents, known ? (p) => can(p) : null);
      const path = href.split("#")[0];
      // Lit only on the agent's own screen: the fallbacks (the agents list,
      // the phone accounts) belong to their Advanced setup rows.
      isActive =
        (path.startsWith("/workflow/") && path !== "/workflow/create" && isWithin(pathname, path)) ||
        // With several agents the row links to the list, but any agent's own
        // screen of this kind is still this row.
        isWorkspaceAgentScreen(pathname, item.agentRow === "facts" ? "facts" : "deployment");
    } else {
      // An agent screen the main menu owns lights its own row, not "Voice agents".
      isActive = !isWorkspaceAgentScreen(pathname) && isNavRowActive(item.url, pathname, returnTo);
    }
    return {
      ...item,
      badge: item.url === FOLLOW_UPS_URL ? (openFollowUps ?? undefined) : item.badge,
      href,
      isActive,
      showWarningDot: Boolean(item.showsTelephonyWarning && hasTelephonyWarning),
    };
  };

  return getNavSections(featureFlags)
    .map((section) => ({ ...section, items: section.items.filter(allowed).map(resolve) }))
    .filter((section) => section.items.length > 0);
}
