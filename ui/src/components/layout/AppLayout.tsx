"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import React, { ReactNode, useEffect, useRef, useState } from "react";

import { NoAccess } from "@/components/auth/NoAccess";
import { LowBalanceBanner } from "@/components/billing/LowBalanceBanner";
import { NoOrganizationNotice } from "@/components/privacy/NoOrganizationNotice";
import {
  PendingDeletionBanner,
  PendingDeletionNotice,
} from "@/components/privacy/PendingDeletionBanner";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { SidebarProvider } from "@/components/ui/sidebar";
import { featureForRoute } from "@/config/features";
import { AgentShellProvider } from "@/context/AgentShellContext";
import { useAppConfig } from "@/context/AppConfigContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useFeatureFlags, useFeatureFlagsLoaded } from "@/hooks/useFeatureFlags";
import { cn } from "@/lib/utils";

import { AgentTestRail } from "./AgentTestRail";
import { AppSidebar } from "./AppSidebar";
import { AppTopBar } from "./AppTopBar";
import { hidesTabBar, MobileTabBar } from "./MobileTabBar";
import { getRequiredPermission } from "./navConfig";
import { PageActionsSlotProvider } from "./PageActionsSlot";
import { PageHeadingProvider } from "./pageHeading";
import { useShellChrome } from "./shellContext";
import { WelcomeToast } from "./WelcomeToast";
import { WorkspaceAgentsProvider } from "./workspaceAgents";

function BackendStatusBanner() {
  const { config, loading, refresh } = useAppConfig();

  if (!config || config.backendStatus === "reachable") {
    return null;
  }

  const backendUrl = config.backendUrl && config.backendUrl !== "unknown"
    ? config.backendUrl
    : "the configured backend";
  const message = config.backendMessage || `Backend is not reachable at ${backendUrl}.`;

  return (
    <div
      role="alert"
      className="border-b border-amber/40 bg-amber-dim px-4 py-3 text-foreground"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold">Backend connection failed</p>
            <p className="break-words text-sm">{message}</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          disabled={loading}
          className="h-8 shrink-0 border-amber/50 bg-transparent text-amber hover:bg-amber-dim"
        >
          <RefreshCw className="h-4 w-4" />
          Retry
        </Button>
      </div>
    </div>
  );
}

/** The content panel's id: the skip link's target. */
export const MAIN_CONTENT_ID = "main-content";

/**
 * After moving to another screen: start the content panel (the scroll
 * container) at the top, and — if focus was left on the link just used, in
 * the nav or the header — move it to the content, so keyboard and screen
 * reader users land on the new screen rather than back at the top of the nav
 * (or on the phone tab bar).
 * The first load and changes to the query string (filters, tabs) are left
 * alone.
 */
function useRouteChangeFocus(pathname: string, main: React.RefObject<HTMLElement | null>) {
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    const panel = main.current;
    if (!panel) return;
    panel.scrollTop = 0;
    const active = document.activeElement;
    const focusLeftBehind =
      !active ||
      active === document.body ||
      Boolean(active.closest("[data-sidebar], header, [data-slot='sidebar'], [data-mobile-tab-bar]")) ||
      !active.isConnected;
    if (focusLeftBehind && !panel.contains(active)) {
      panel.focus({ preventScroll: true });
    }
  }, [pathname, main]);
}

interface AppLayoutProps {
  children: ReactNode;
}

/**
 * The app shell from the design canvas
 * (app-doc/claude-design/Failte AI v2.dc.html):
 *
 *   ┌──────────────────────────────────────────────┐  46px header — brand,
 *   │ Fallcha.ai / Workspace / Page strapline  ⋯ ● │  breadcrumb, actions, you
 *   ├────────────┬──────────────────┬──────────────┤
 *   │  nav panel │  content panel   │  test rail   │  14px gutter + 14px gap,
 *   └────────────┴──────────────────┴──────────────┘  all rounded surfaces
 *
 * The viewport never scrolls: the content panel is the scroll container, so the
 * header and nav stay put. Agent routes run the SAME shell — the canvas keeps
 * the header, the nav panel and the test rail fixed there and only swaps the
 * centre panel — so the third column is the only structural difference.
 */
const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const pathname = usePathname();
  const router = useRouter();
  const [actionsSlot, setActionsSlot] = useState<HTMLDivElement | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);
  useRouteChangeFocus(pathname, mainRef);

  // A page of a product area switched off for this organisation goes to
  // Overview. Middleware already redirects areas that are off for everyone;
  // this applies the organisation's own switch once it has been read.
  const featureFlags = useFeatureFlags();
  const featureFlagsLoaded = useFeatureFlagsLoaded();
  const routeFeature = featureForRoute(pathname);
  const awaitingFeature = routeFeature !== null && !featureFlagsLoaded;
  const featureSwitchedOff = routeFeature !== null && featureFlagsLoaded && !featureFlags[routeFeature];
  useEffect(() => {
    if (featureSwitchedOff) {
      router.replace("/overview");
    }
  }, [featureSwitchedOff, router]);

  // Hide the shell for root (/), /handler routes (Stack Auth), /auth routes
  // and invitation landing pages.
  const shouldShowShell =
    pathname !== "/" &&
    !pathname.startsWith("/handler") &&
    !pathname.startsWith("/auth") &&
    !pathname.startsWith("/invite");

  // A run's detail screen is a read-only record, and a run opened from a
  // workspace list stays in the workspace — neither gets the live test rail.
  const { showTestRail } = useShellChrome();
  // Phones get the tab bar instead of the sidebar, except on the full-screen
  // conversation diagram.
  const showTabBar = !hidesTabBar(pathname);

  // The API enforces roles; this just replaces a screen full of 403s with an
  // explanation. A restricted screen waits for the role so it doesn't mount
  // and fire requests the role can't make; if the role can't be loaded at all
  // the screen renders and the API remains the guard.
  const {
    role,
    can,
    loading: orgLoading,
    orgContext,
    organizationUnavailable,
  } = useOrgConfig();
  const requiredPermission = getRequiredPermission(pathname);
  const awaitingRole = requiredPermission !== null && role === null && orgLoading;
  const blocked = role !== null && requiredPermission !== null && !can(requiredPermission);
  // While the organization is pending deletion its API answers 423 everywhere
  // but the export, the cancel and your own account (Settings and Your
  // account); show why instead of a screen of errors.
  // No organization to work in (erased, or none left): explain instead of
  // screens of errors. Your account still works without one under local auth.
  const noOrganization =
    organizationUnavailable === "erased" ||
    (organizationUnavailable === "none" &&
      !["/account", "/superadmin", "/impersonate"].some((p) => pathname.startsWith(p)));
  const closedForDeletion =
    Boolean(orgContext?.deletion?.pending) &&
    // General settings only: the other /settings screens call blocked APIs.
    pathname !== "/settings" &&
    !pathname.startsWith("/account");

  // Always render a single SidebarProvider and branch INSIDE it, so the
  // provider (and its open/collapsed state) survives navigation between the
  // shell, the agent editor and the signed-out routes.
  return (
    <SidebarProvider defaultOpen>
      <AgentShellProvider>
        {!shouldShowShell ? (
          <div className="app-surface w-full flex-1">
            <BackendStatusBanner />
            {children}
          </div>
        ) : (
          <PageActionsSlotProvider slot={actionsSlot}>
            <WorkspaceAgentsProvider>
            <PageHeadingProvider>
              <div className="app-surface flex h-svh w-full flex-col overflow-hidden">
                <a
                  href={`#${MAIN_CONTENT_ID}`}
                  className="sr-only rounded-md bg-panel px-3 py-2 text-sm font-medium text-foreground shadow-panel focus:not-sr-only focus:fixed focus:left-3 focus:top-2 focus:z-[60] focus:outline-none focus:ring-[3px] focus:ring-ring/50"
                >
                  Skip to main content
                </a>
                <AppTopBar actionsSlotRef={setActionsSlot} />
                <WelcomeToast />

                {/* On phones the content stops above the fixed tab bar. */}
                <div
                  className={cn(
                    "flex min-h-0 flex-1 gap-3.5 px-3.5 pb-3.5 md:pl-0",
                    showTabBar && "max-md:pb-[calc(64px+env(safe-area-inset-bottom)+0.875rem)]",
                  )}
                >
                  <AppSidebar />
                  <main
                    ref={mainRef}
                    id={MAIN_CONTENT_ID}
                    tabIndex={-1}
                    className="app-content-panel relative min-w-0 flex-1 overflow-y-auto rounded-xl border border-line bg-panel outline-none [scrollbar-gutter:stable]"
                  >
                    <BackendStatusBanner />
                    <PendingDeletionBanner />
                    <LowBalanceBanner />
                    {noOrganization && organizationUnavailable ? (
                      <NoOrganizationNotice reason={organizationUnavailable} />
                    ) : awaitingRole || awaitingFeature || featureSwitchedOff ? (
                      // Hold the screen's shape while the role loads, not a blank panel.
                      <PageSkeleton variant="list" />
                    ) : blocked ? (
                      <NoAccess role={role} />
                    ) : closedForDeletion ? (
                      <PendingDeletionNotice />
                    ) : (
                      children
                    )}
                  </main>
                  {showTestRail && <AgentTestRail />}
                </div>
                {showTabBar && <MobileTabBar />}
              </div>
            </PageHeadingProvider>
            </WorkspaceAgentsProvider>
          </PageActionsSlotProvider>
        )}
      </AgentShellProvider>
    </SidebarProvider>
  );
};

export default AppLayout;
