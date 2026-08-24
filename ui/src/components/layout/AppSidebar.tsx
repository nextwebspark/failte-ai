"use client";

import { AlertTriangle, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";

import { BrandLogo } from "@/components/BrandLogo";
import ThemeToggle from "@/components/ThemeSwitcher";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAgentShellOptional } from "@/context/AgentShellContext";
import { useTelephonyConfigWarnings } from "@/context/TelephonyConfigWarningsContext";
import { cn } from "@/lib/utils";

import { AGENT_NAV_SECTIONS, agentHref, agentSectionFor } from "./agentNav";
import { NAV_SECTIONS } from "./navConfig";

const TELEPHONY_WARNING_COPY = "Action required";

/** What a nav row needs, whichever nav it came from. */
type SidebarLinkProps = {
  title: string;
  url: string;
  icon: React.ComponentType<{ className?: string }>;
  isActive: boolean;
  showWarningDot?: boolean;
};

/**
 * The canvas's nav panel: nothing but grouped destinations and the theme row
 * (app-doc/claude-design/Failte AI v2.dc.html, the <nav> element). Brand,
 * version, workspace switcher and the account menu live in AppTopBar.
 *
 * Two navs share this panel, exactly as the canvas does. On a workspace route
 * it lists NAV_SECTIONS; on an agent route it swaps to a "back to the
 * workspace" row, the agent's identity, and AGENT_NAV_SECTIONS — the header
 * and the test rail either side of it never move.
 *
 * `docked` positions the panel under that 46px header, in the 14px gutter the
 * canvas body uses.
 */
export function AppSidebar({ docked = true }: { docked?: boolean }) {
  const pathname = usePathname();
  const { state, isMobile, setOpenMobile } = useSidebar();
  const agentShell = useAgentShellOptional();
  const {
    telnyxMissingWebhookPublicKeyCount,
    vonageMissingSignatureSecretCount,
  } = useTelephonyConfigWarnings();
  const hasTelephonyWarning =
    telnyxMissingWebhookPublicKeyCount > 0 ||
    vonageMissingSignatureSecretCount > 0;
  const isCollapsed = !isMobile && state === "collapsed";

  const handleMobileNavClick = () => {
    if (isMobile) {
      setOpenMobile(false);
    }
  };

  const SidebarLink = ({ title, url, icon: Icon, isActive, showWarningDot }: SidebarLinkProps) => {
    const tooltip = {
      children: (
        <div className="notranslate" translate="no">
          <p>{title}</p>
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
          "h-auto gap-2.5 rounded-[7px] px-2.5 py-2 text-[13.5px] font-normal text-ink-2",
          "transition-colors hover:bg-panel-2 hover:text-foreground",
          isActive &&
            "bg-sky-dim font-semibold text-sky hover:bg-sky-dim hover:text-sky"
        )}
      >
        <Link
          href={url}
          aria-current={isActive ? "page" : undefined}
          onClick={handleMobileNavClick}
          className={cn(isCollapsed && "justify-center")}
          translate="no"
        >
          <Icon className={cn("h-4 w-4 shrink-0", isActive && "text-sky")} />
          <span
            className={cn("notranslate min-w-0 flex-1 truncate", isCollapsed && "sr-only")}
            translate="no"
          >
            {title}
          </span>
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

  const workspaceNav = NAV_SECTIONS.map((section) => (
    <SidebarGroup key={section.label ?? "overview"} className="px-2 py-0">
      {section.label && (
        <SidebarGroupLabel
          className={cn(
            "notranslate h-auto px-2.5 pb-1.5 pt-3.5 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-3",
            isCollapsed && "hidden"
          )}
          translate="no"
        >
          {section.label}
        </SidebarGroupLabel>
      )}
      <SidebarMenu>
        {section.items.map((item) => (
          <SidebarMenuItem key={item.title}>
            <SidebarLink
              title={item.title}
              url={item.url}
              icon={item.icon}
              isActive={pathname.startsWith(item.url)}
              showWarningDot={item.showsTelephonyWarning && hasTelephonyWarning}
            />
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  ));

  const activeAgentSegment = agentShell ? agentSectionFor(pathname)?.segment ?? "" : "";

  const agentNav = agentShell && (
    <>
      {/* "All voice agents" + the agent's identity, per the canvas's inAgent
          block. Both are hidden when the panel collapses to icons. */}
      <SidebarGroup className="px-2 py-0">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              tooltip={{ children: <p>All voice agents</p> }}
              className={cn(
                "h-auto gap-2.5 rounded-[7px] px-2.5 py-2 text-[13px] font-medium text-ink-2",
                "transition-colors hover:bg-panel-2 hover:text-foreground"
              )}
            >
              <Link href="/workflow" onClick={handleMobileNavClick} translate="no">
                <ArrowLeft className="h-4 w-4 shrink-0" />
                <span className={cn("notranslate truncate", isCollapsed && "sr-only")}>
                  All voice agents
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
              <span
                className={cn(
                  "mt-1.5 inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.05em]",
                  agentShell.agent.versionStatus === "published"
                    ? "bg-ok-dim text-ok"
                    : "bg-amber-dim text-amber"
                )}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {agentShell.agent.versionStatus}
              </span>
            )}
          </div>
        </>
      )}

      {AGENT_NAV_SECTIONS.map((section) => (
        <SidebarGroup key={section.label ?? "agent"} className="px-2 py-0">
          {section.label && (
            <SidebarGroupLabel
              className={cn(
                "notranslate h-auto px-2.5 pb-1.5 pt-3.5 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-3",
                isCollapsed && "hidden"
              )}
              translate="no"
            >
              {section.label}
            </SidebarGroupLabel>
          )}
          <SidebarMenu>
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
      {/* Only the undocked layout carries the brand here — the docked shell
          puts it in the app header instead. */}
      {!docked && (
        <SidebarHeader className="px-2 pb-0 pt-1 notranslate" translate="no">
          <Link
            href="/overview"
            className={cn(
              "notranslate flex items-center gap-2 rounded-[7px] px-1.5 py-1",
              isCollapsed && "justify-center px-0"
            )}
            translate="no"
          >
            <BrandLogo mark className="h-[22px] rounded-md" />
            <span
              className={cn(
                "font-mono text-[13px] font-semibold leading-none",
                isCollapsed && "sr-only"
              )}
            >
              Failte<span className="font-normal opacity-60">AI</span>
            </span>
          </Link>
        </SidebarHeader>
      )}

      <SidebarContent className={cn("notranslate gap-0 pt-3.5", isCollapsed && "px-0")} translate="no">
        {agentShell ? agentNav : workspaceNav}
      </SidebarContent>

      <SidebarFooter
        className={cn(
          "notranslate mx-2 mt-auto border-t border-line-soft px-0 pb-3.5 pt-3",
          isCollapsed && "mx-1"
        )}
        translate="no"
      >
        {isCollapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="notranslate flex justify-center" translate="no">
                <ThemeToggle className="text-ink-2 hover:bg-panel-2 hover:text-foreground" />
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">
              <p>Toggle theme</p>
            </TooltipContent>
          </Tooltip>
        ) : (
          <ThemeToggle
            showLabel
            className="h-auto rounded-[7px] px-2.5 py-2 text-[13.5px] text-ink-2 hover:bg-panel-2 hover:text-foreground"
          />
        )}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
