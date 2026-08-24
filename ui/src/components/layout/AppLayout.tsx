"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { usePathname } from "next/navigation";
import React, { ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AgentShellProvider } from "@/context/AgentShellContext";
import { useAppConfig } from "@/context/AppConfigContext";

import { isAgentRoute } from "./agentNav";
import { AgentTestRail } from "./AgentTestRail";
import { AppSidebar } from "./AppSidebar";
import { AppTopBar } from "./AppTopBar";
import { PageActionsSlotProvider } from "./PageActionsSlot";

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

interface AppLayoutProps {
  children: ReactNode;
}

/**
 * The app shell from the design canvas
 * (app-doc/claude-design/Failte AI v2.dc.html):
 *
 *   ┌──────────────────────────────────────────────┐  46px header — brand,
 *   │ FailteAI / Workspace / Page  strapline   ⋯ ● │  breadcrumb, actions, you
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
  const [actionsSlot, setActionsSlot] = useState<HTMLDivElement | null>(null);

  // Hide the shell for root (/), /handler routes (Stack Auth) and /auth routes.
  const shouldShowShell =
    pathname !== "/" && !pathname.startsWith("/handler") && !pathname.startsWith("/auth");

  const inAgent = isAgentRoute(pathname);

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
            <div className="app-surface flex h-svh w-full flex-col overflow-hidden">
              <AppTopBar actionsSlotRef={setActionsSlot} />

              <div className="flex min-h-0 flex-1 gap-3.5 px-3.5 pb-3.5 md:pl-0">
                <AppSidebar />
                <main className="app-content-panel min-w-0 flex-1 overflow-y-auto rounded-[10px] border border-line bg-panel">
                  <BackendStatusBanner />
                  {children}
                </main>
                {inAgent && <AgentTestRail />}
              </div>
            </div>
          </PageActionsSlotProvider>
        )}
      </AgentShellProvider>
    </SidebarProvider>
  );
};

export default AppLayout;
