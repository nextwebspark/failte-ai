"use client";

import { AlertTriangle, ArrowLeft, ChevronRight, Wrench } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";

import { BrandLogo } from "@/components/BrandLogo";
import ThemeToggle from "@/components/ThemeSwitcher";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { StatusPill, statusTone } from "@/components/ui/status-pill";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAgentShellOptional } from "@/context/AgentShellContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { cn } from "@/lib/utils";
import { workspaceDisplayName } from "@/lib/workspaceName";

import { AGENT_NAV_SECTIONS, agentHref, agentSectionFor } from "./agentNav";
import { initialsOf, memberName } from "./memberIdentity";
import { type ResolvedNavItem, useWorkspaceNav } from "./useWorkspaceNav";
import { useWorkspaceAgents } from "./workspaceAgents";

const TELEPHONY_WARNING_COPY = "Action required";

/** The agent's status in owner words, matching the agent list ("Live"). */
const AGENT_STATUS_LABEL: Record<string, string> = {
  published: "Live",
  draft: "Draft",
  archived: "Archived",
};

/** Remembers whether "Advanced setup" was left open (closed by default). */
export const ADVANCED_OPEN_KEY = "lightmove.nav.advancedOpen";

function readAdvancedOpen(): boolean {
  try {
    return globalThis.localStorage?.getItem(ADVANCED_OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

function writeAdvancedOpen(open: boolean) {
  try {
    globalThis.localStorage?.setItem(ADVANCED_OPEN_KEY, open ? "1" : "0");
  } catch {
    // Storage unavailable: the row just starts closed next time.
  }
}

/** What a nav row needs, whichever nav it came from. */
type SidebarLinkProps = {
  title: string;
  url: string;
  icon: React.ComponentType<{ className?: string }>;
  isActive: boolean;
  showWarningDot?: boolean;
  badge?: number;
};

const GROUP_LABEL_CLASS =
  "notranslate h-auto px-2.5 pb-1 pt-3.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3";

/** "4 open" for screen readers; the badge itself only shows the number. */
function badgeLabel(title: string, count: number): string {
  return title === "Follow-ups" ? `${count} open` : `${count} new`;
}

/**
 * The left nav from the 5 November redesign (mocks/home.png):
 *
 *   [business card]          workspace name
 *   Home · Calls · Follow-ups · Bookings · Reports
 *   YOUR AGENT               What your agent knows · Phone number · Settings
 *   Advanced setup ›         every builder screen, folded away (remembered)
 *   ─────────────
 *   [you] name, role         dark mode
 *
 * On an agent route it swaps to that agent's own nav: a way back, the
 * agent's name and status, then AGENT_NAV_SECTIONS. The header and the test
 * rail either side of it never move.
 *
 * `docked` positions the panel under the 46px header, in the 14px gutter the
 * canvas body uses.
 */
export function AppSidebar({ docked = true }: { docked?: boolean }) {
  const pathname = usePathname();
  const { state, isMobile, setOpenMobile } = useSidebar();
  const agentShell = useAgentShellOptional();
  const isCollapsed = !isMobile && state === "collapsed";
  const { role, orgContext } = useOrgConfig();
  const { user } = useAuth();
  const sections = useWorkspaceNav();
  const agents = useWorkspaceAgents();

  // "Advanced setup" starts closed, remembers the member's choice, and is
  // open whenever one of its screens is the current one.
  const [advancedOpen, setAdvancedOpen] = useState(false);
  useEffect(() => setAdvancedOpen(readAdvancedOpen()), []);
  const advancedActive = sections.some((s) => s.collapsible && s.items.some((item) => item.isActive));
  const toggleAdvanced = (open: boolean) => {
    setAdvancedOpen(open);
    writeAdvancedOpen(open);
  };

  const handleMobileNavClick = () => {
    if (isMobile) {
      setOpenMobile(false);
    }
  };

  // The phone menu also closes on any other move between screens — Back,
  // Forward, or a link inside the page — so it never covers the new screen.
  useEffect(() => {
    setOpenMobile(false);
  }, [pathname, setOpenMobile]);

  const SidebarLink = ({ title, url, icon: Icon, isActive, showWarningDot, badge }: SidebarLinkProps) => {
    const count = badge && badge > 0 ? badge : 0;
    const tooltip = {
      children: (
        <div className="notranslate" translate="no">
          <p>
            {title}
            {count > 0 && ` (${badgeLabel(title, count)})`}
          </p>
          {showWarningDot && (
            <p className="text-amber">{TELEPHONY_WARNING_COPY}</p>
          )}
        </div>
      ),
    };

    // The canvas marks an attention-needing row with a 6px amber dot pushed to
    // the end of the row; collapsed, it rides the icon's top-right corner.
    const warningIndicator = isCollapsed ? (
      <AlertTriangle
        aria-label="Action required on a telephony configuration"
        className="absolute -right-0.5 -top-0.5 h-3 w-3 text-amber"
      />
    ) : (
      <span
        aria-label="Action required on a telephony configuration"
        role="img"
        className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-amber"
      />
    );

    return (
      <SidebarMenuButton
        asChild
        tooltip={tooltip}
        className={cn(
          "h-auto gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium text-ink-2",
          // 44px rows for fingers in the phone menu.
          isMobile && "min-h-11 py-2.5 text-[14.5px]",
          "transition-colors hover:bg-panel-2 hover:text-foreground",
          isActive &&
            "bg-brand-dim font-semibold text-brand hover:bg-brand-dim hover:text-brand"
        )}
      >
        <Link
          href={url}
          aria-current={isActive ? "page" : undefined}
          onClick={handleMobileNavClick}
          className={cn("relative", isCollapsed && "justify-center")}
          translate="no"
        >
          <Icon className={cn("h-[17px] w-[17px] shrink-0", isActive && "text-brand")} />
          <span
            className={cn("notranslate min-w-0 flex-1 truncate", isCollapsed && "sr-only")}
            translate="no"
          >
            {title}
          </span>
          {count > 0 && (
            <span
              className={cn(
                "grid min-w-5 place-items-center rounded-full bg-amber px-1.5 text-[11px] font-bold leading-[18px] text-white",
                isCollapsed && "absolute -right-1 -top-1 min-w-4 px-1 text-[10px] leading-4"
              )}
            >
              {count}
              <span className="sr-only"> {badgeLabel(title, count).replace(/^\d+ /, "")}</span>
            </span>
          )}
          {showWarningDot && (
            isCollapsed ? (
              warningIndicator
            ) : (
              <Tooltip>
                <TooltipTrigger asChild>
                  {warningIndicator}
                </TooltipTrigger>
                <TooltipContent side="right">
                  <p>{TELEPHONY_WARNING_COPY}</p>
                </TooltipContent>
              </Tooltip>
            )
          )}
        </Link>
      </SidebarMenuButton>
    );
  };

  const navRow = (item: ResolvedNavItem) => (
    <SidebarMenuItem key={`${item.title}-${item.url}`}>
      <SidebarLink
        title={item.title}
        url={item.href}
        icon={item.icon}
        isActive={item.isActive}
        showWarningDot={item.showWarningDot}
        badge={item.badge}
      />
    </SidebarMenuItem>
  );

  const advancedIsOpen = advancedOpen || advancedActive;

  const workspaceNav = sections.map((section) =>
    section.collapsible ? (
      <SidebarGroup key={section.id} className="px-2 py-0 pt-2">
        <Collapsible open={advancedIsOpen} onOpenChange={toggleAdvanced}>
          <SidebarMenu>
            <SidebarMenuItem>
              <CollapsibleTrigger asChild>
                <SidebarMenuButton
                  tooltip={{ children: <p>{section.label}</p> }}
                  className={cn(
                    "h-auto gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium text-ink-3",
                    isMobile && "min-h-11 py-2.5 text-[14.5px]",
                    "transition-colors hover:bg-panel-2 hover:text-foreground",
                    isCollapsed && "justify-center"
                  )}
                >
                  <Wrench className="h-[17px] w-[17px] shrink-0" aria-hidden />
                  <span className={cn("notranslate min-w-0 flex-1 truncate text-left", isCollapsed && "sr-only")}>
                    {section.label}
                  </span>
                  {!isCollapsed && (
                    <ChevronRight
                      aria-hidden
                      className={cn(
                        "h-3.5 w-3.5 shrink-0 transition-transform motion-reduce:transition-none",
                        advancedIsOpen && "rotate-90"
                      )}
                    />
                  )}
                </SidebarMenuButton>
              </CollapsibleTrigger>
            </SidebarMenuItem>
          </SidebarMenu>
          <CollapsibleContent>
            <SidebarMenu className={cn("mt-0.5 gap-0.5", !isCollapsed && "pl-3")}>
              {section.items.map(navRow)}
            </SidebarMenu>
          </CollapsibleContent>
        </Collapsible>
      </SidebarGroup>
    ) : (
      <SidebarGroup key={section.id} className="px-2 py-0">
        {section.label && (
          <SidebarGroupLabel className={cn(GROUP_LABEL_CLASS, isCollapsed && "hidden")} translate="no">
            {section.label}
          </SidebarGroupLabel>
        )}
        <SidebarMenu className="gap-0.5">{section.items.map(navRow)}</SidebarMenu>
      </SidebarGroup>
    )
  );

  const activeAgentSegment = agentShell ? agentSectionFor(pathname)?.segment ?? "" : "";
  // With one agent the workspace IS that agent's business, so "back" is Home.
  // With several, back to the list to pick another.
  const back = agents !== null && agents.length > 1
    ? { href: "/workflow", label: "All voice agents" }
    : { href: "/overview", label: "Back to Home" };

  const agentNav = agentShell && (
    <>
      <SidebarGroup className="px-2 py-0">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip={{ children: <p>{back.label}</p> }}
              className={cn(
                "h-auto gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium text-ink-2",
                isMobile && "min-h-11",
                "transition-colors hover:bg-panel-2 hover:text-foreground"
              )}
            >
              <Link href={back.href} onClick={handleMobileNavClick} translate="no">
                <ArrowLeft className="h-4 w-4 shrink-0" />
                <span className={cn("notranslate truncate", isCollapsed && "sr-only")}>
                  {back.label}
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroup>

      {!isCollapsed && (
        <>
          <div className="mx-3 mt-2.5 h-px bg-line-soft" />
          <div className="px-4 pb-1 pt-2.5">
            <p className="truncate text-[13.5px] font-semibold text-foreground" title={agentShell.agent?.name}>
              {agentShell.agent?.name ?? "…"}
            </p>
            {agentShell.agent?.versionStatus && (
              <StatusPill
                tone={statusTone(agentShell.agent.versionStatus)}
                dot
                className="mt-1.5 px-2 py-0.5 text-[10px]"
              >
                {AGENT_STATUS_LABEL[agentShell.agent.versionStatus] ?? agentShell.agent.versionStatus}
              </StatusPill>
            )}
          </div>
        </>
      )}

      {AGENT_NAV_SECTIONS.map((section) => (
        <SidebarGroup key={section.label ?? "agent"} className="px-2 py-0">
          {section.label && (
            <SidebarGroupLabel className={cn(GROUP_LABEL_CLASS, isCollapsed && "hidden")} translate="no">
              {section.label}
            </SidebarGroupLabel>
          )}
          <SidebarMenu className="gap-0.5">
            {section.items.map((item) => (
              <SidebarMenuItem key={item.title}>
                <SidebarLink
                  title={item.title}
                  url={agentHref(agentShell.workflowId, item.segment)}
                  icon={item.icon}
                  isActive={activeAgentSegment === item.segment}
                />
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      ))}
    </>
  );

  const workspaceName = workspaceDisplayName(orgContext?.organization_name);
  const person = memberName(user);

  return (
    <Sidebar
      collapsible="icon"
      variant="floating"
      className={cn(
        "app-sidebar-dock",
        docked
          ? "app-sidebar-docked inset-y-auto bottom-3.5 left-0 h-auto p-0 pl-3.5"
          : "py-3.5"
      )}
    >
      <SidebarHeader className={cn("notranslate gap-2 px-2.5 pb-0 pt-2.5", isCollapsed && "px-1.5")} translate="no">
        {/* Only the undocked layout carries the brand here — the docked shell
            puts it in the app header instead. */}
        {!docked && (
          <Link
            href="/overview"
            className={cn(
              "notranslate flex items-center gap-2 rounded-md px-1.5 py-1",
              isCollapsed && "justify-center px-0"
            )}
            translate="no"
          >
            {isCollapsed ? <BrandLogo mark size={24} /> : <BrandLogo size={24} />}
          </Link>
        )}
        {/* The business this workspace is: only what is stored, its name. */}
        {!agentShell && (
          <div
            className={cn(
              "flex items-center gap-2.5 rounded-[10px] border border-line px-2.5 py-2",
              isCollapsed && "justify-center border-0 p-0"
            )}
            title={isCollapsed ? workspaceName : undefined}
          >
            <span
              aria-hidden
              className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-brand-dim text-[12px] font-bold text-brand"
            >
              {initialsOf(workspaceName, "W")}
            </span>
            <p className={cn("min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground", isCollapsed && "sr-only")}>
              {workspaceName}
            </p>
          </div>
        )}
      </SidebarHeader>

      <SidebarContent className={cn("notranslate gap-0 pt-2.5", isCollapsed && "px-0")} translate="no">
        {agentShell ? agentNav : workspaceNav}
      </SidebarContent>

      <SidebarFooter
        className={cn(
          "notranslate mx-2 mt-auto border-t border-line-soft px-0.5 pb-3 pt-3",
          isCollapsed && "mx-1 px-0"
        )}
        translate="no"
      >
        <div className={cn("flex items-center gap-2.5", isCollapsed && "flex-col gap-2")}>
          {person && (
            <span
              aria-hidden
              title={isCollapsed ? person : undefined}
              className="grid size-7 shrink-0 place-items-center rounded-full bg-panel-2 text-[11px] font-bold text-ink-2"
            >
              {initialsOf(person)}
            </span>
          )}
          <div className={cn("min-w-0 flex-1 leading-tight", isCollapsed && "sr-only")}>
            <p className="truncate text-[12.5px] text-foreground" title={person}>
              {person || "Signed in"}
            </p>
            {role && <p className="truncate text-[11.5px] text-ink-3">{ROLE_LABELS[role]}</p>}
          </div>
          <ThemeToggle className="size-8 shrink-0 text-ink-2 hover:bg-panel-2 hover:text-foreground" />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
