"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { usePathname } from "next/navigation";
import React, { ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useAppConfig } from "@/context/AppConfigContext";

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
 * The workspace ("org level") shell from the design canvas
 * (app-doc/claude-design/Failte AI v2.dc.html):
 *
 *   ┌──────────────────────────────────────────────┐  46px header — brand,
 *   │ FailteAI / Workspace / Page  strapline   ⋯ ● │  breadcrumb, actions, you
 *   ├────────────┬─────────────────────────────────┤
 *   │  nav panel │  content panel                  │  14px gutter + 14px gap,
 *   └────────────┴─────────────────────────────────┘  both rounded surfaces
 *
 * The viewport never scrolls: the content panel is the scroll container, so the
 * header and nav stay put. The workflow editor keeps the previous full-height
 * layout — it is an agent-level screen with a header of its own.
 */
const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const pathname = usePathname();
  const [actionsSlot, setActionsSlot] = useState<HTMLDivElement | null>(null);

  // Check if current route should have sidebar
  // Hide sidebar for root (/), /handler routes (Stack Auth routes), and /auth routes
  const shouldShowSidebar = pathname !== "/" && !pathname.startsWith("/handler") && !pathname.startsWith("/auth");

  // Only match the exact editor page /workflow/<id>, not sub-routes like /workflow/<id>/runs
  const isWorkflowEditor = /^\/workflow\/\d+$/.test(pathname);

  // Always render a single SidebarProvider and branch INSIDE it, so the
  // provider (and its open/collapsed state) survives navigation between the
  // shell, the workflow editor and the signed-out routes.
  return (
    <SidebarProvider defaultOpen>
      {!shouldShowSidebar ? (
        <div className="app-surface w-full flex-1">
          <BackendStatusBanner />
          {children}
        </div>
      ) : isWorkflowEditor ? (
        <div className="flex min-h-screen w-full">
          <AppSidebar docked={false} />
          <SidebarInset className="flex-1">
            <BackendStatusBanner />
            <main className="app-surface flex-1">{children}</main>
          </SidebarInset>
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
            </div>
          </div>
        </PageActionsSlotProvider>
      )}
    </SidebarProvider>
  );
};

export default AppLayout;
