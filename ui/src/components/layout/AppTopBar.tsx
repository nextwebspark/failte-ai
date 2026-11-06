"use client";

import { ArrowUpCircle, Bot, LogOut, Menu, Settings, UserRound, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";

import { BrandLogo } from "@/components/BrandLogo";
import { LocalOrgSwitcher } from "@/components/layout/LocalOrgSwitcher";
import { SidebarTeamSwitcher } from "@/components/layout/SidebarTeamSwitcher";
import { firstSettingsUrl } from "@/components/settings/settingsNav";
import { SupportLink } from "@/components/SupportLink";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSidebar } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAgentShellOptional } from "@/context/AgentShellContext";
import { useAppConfig } from "@/context/AppConfigContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useLatestReleaseVersion } from "@/hooks/useLatestReleaseVersion";
import type { LocalUser } from "@/lib/auth";
import { useAuth } from "@/lib/auth";
import { type Permission, ROLE_LABELS } from "@/lib/auth/roles";

import { agentSectionFor } from "./agentNav";
import { getPageMeta } from "./navConfig";
import { usePageHeadingOwned } from "./pageHeading";
import { useShellChrome } from "./shellContext";

type AccountLink = { href: string; label: string; icon: typeof Settings };

/**
 * The account menu's links, minus the ones the caller's role can't open.
 * `can` is null while the role loads: only the always-open links show then.
 */
export function accountMenuLinks(
  provider: string | undefined,
  can: ((...permissions: Permission[]) => boolean) | null,
): AccountLink[] {
  const links: AccountLink[] = [];
  if (provider === "stack") {
    links.push({ href: "/handler/account-settings", label: "Account settings", icon: Settings });
  }
  links.push({ href: "/account", label: "Your account", icon: UserRound });
  if (can?.("members:read")) {
    links.push({ href: "/team", label: "Team", icon: Users });
  }
  if (can) {
    const settings = firstSettingsUrl(can);
    // With no settings screen to open, Settings would only repeat "Your account".
    if (settings !== "/account") {
      links.push({ href: settings, label: "Settings", icon: Settings });
    }
  }
  return links;
}

/**
 * The canvas's 46px app header (app-doc/claude-design/Failte AI v2.dc.html):
 *
 *   [mark] Fallcha.ai / Acme Voice / Page title  strapline   … [actions] [you]
 *
 * It owns the identity the sidebar used to carry (brand, version, workspace
 * switcher, account menu) so the nav panel below can be nothing but nav, and
 * it exposes the slot pages portal their primary action into (PageActions).
 */
export function AppTopBar({
  actionsSlotRef,
}: {
  actionsSlotRef: (node: HTMLDivElement | null) => void;
}) {
  const pathname = usePathname();
  const { provider, logout, user } = useAuth();
  const { config } = useAppConfig();
  const { toggleSidebar } = useSidebar();
  const agentShell = useAgentShellOptional();
  const { returnTo, workspaceMode, showTestRail } = useShellChrome();

  // On an agent route the canvas prints the AGENT as the title and the open
  // section as the strapline — the nav below swaps with it.
  const agentSection = agentShell ? agentSectionFor(pathname) : null;
  // A run opened from a workspace list keeps that list's breadcrumb; the run
  // itself becomes the strapline.
  const runId = workspaceMode ? pathname.split("/").pop() : null;
  const meta = agentShell
    ? {
        title: agentShell.agent?.name ?? "Voice agent",
        subtitle: agentSection?.title,
      }
    : workspaceMode && returnTo
      ? { ...getPageMeta(returnTo), subtitle: runId ? `Run ${runId}` : undefined }
      : getPageMeta(pathname);
  const uiVersion = config?.uiVersion;
  // A screen that prints its own title owns the h1 (and shows its own
  // one-line description), so the header's copy becomes a plain breadcrumb.
  const pageOwnsHeading = usePageHeadingOwned();
  const TitleTag = pageOwnsHeading ? "p" : "h1";

  // Update check is OSS-only — cloud deployments are upgraded for the user.
  const { latest: latestRelease, isBehind } = useLatestReleaseVersion(uiVersion, {
    enabled: config?.deploymentMode === "oss",
  });

  const { role, can } = useOrgConfig();

  const accountLinks = accountMenuLinks(provider, role === null ? null : can);

  const displayIdentity =
    user?.displayName ||
    (user as { primaryEmail?: string } | undefined)?.primaryEmail ||
    (user as LocalUser | undefined)?.email ||
    "";
  const userInitials =
    displayIdentity
      .split(/[\s@]/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s: string) => s[0]?.toUpperCase())
      .join("") || "U";

  const separator = (
    <span aria-hidden className="select-none text-xs text-ink-3 opacity-40">
      /
    </span>
  );

  return (
    // Below md the header wraps: identity stays on the first row and the
    // screen's actions drop below it, wrapping rather than running off-screen.
    <header className="flex min-h-[46px] flex-none flex-wrap items-center gap-2 px-3.5 py-1.5 md:h-[46px] md:flex-nowrap md:py-0">
      <Button
        variant="ghost"
        size="icon"
        onClick={toggleSidebar}
        aria-label="Toggle navigation"
        className="size-10 shrink-0 text-ink-3 hover:text-foreground md:size-7"
      >
        <Menu className="h-4 w-4" />
      </Button>

      <Link
        href="/overview"
        className="notranslate flex shrink-0 items-center gap-1.5 rounded-md py-1 pl-1 pr-1.5"
        translate="no"
      >
        {/* The kit lockup, mark at its 24px minimum. */}
        <BrandLogo size={24} />
      </Link>

      {uiVersion && (
        <span className="hidden font-mono text-[11px] text-ink-3 lg:inline">
          v{uiVersion}
        </span>
      )}
      {isBehind && latestRelease && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="hidden items-center gap-1 rounded-md bg-amber-dim px-1.5 py-0.5 font-mono text-[10px] font-medium leading-none text-amber lg:inline-flex">
              <ArrowUpCircle className="h-3 w-3" />
              Update
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>Update available: {latestRelease}</p>
          </TooltipContent>
        </Tooltip>
      )}

      {provider === "stack" ? (
        <>
          <span className="hidden sm:inline">{separator}</span>
          <div className="hidden min-w-0 max-w-[200px] sm:block">
            <SidebarTeamSwitcher triggerClassName="h-7 w-full justify-start gap-1.5 border-0 bg-transparent px-1.5 text-[13px] font-medium text-ink-3 shadow-none hover:text-foreground focus-visible:ring-0" />
          </div>
        </>
      ) : (
        <>
          <span className="hidden sm:inline">{separator}</span>
          <div className="hidden min-w-0 max-w-[220px] sm:block">
            <LocalOrgSwitcher />
          </div>
        </>
      )}

      <span className="hidden sm:inline">{separator}</span>
      {/* Narrow, the title takes the room that's left and truncates rather
          than pushing the help and account buttons onto a second row. */}
      <TitleTag className="min-w-0 flex-1 basis-0 truncate whitespace-nowrap text-sm font-semibold text-foreground md:flex-none md:basis-auto">
        {meta.title}
      </TitleTag>
      {meta.subtitle && !pageOwnsHeading && (
        <p className="hidden truncate whitespace-nowrap text-xs text-ink-3 xl:block">
          {meta.subtitle}
        </p>
      )}

      {/* Screens portal their primary action in here — see PageActions. */}
      <div
        ref={actionsSlotRef}
        className="order-last flex w-full min-w-0 flex-wrap items-center gap-2 empty:hidden md:order-none md:ml-auto md:w-auto md:flex-nowrap md:justify-end md:empty:flex"
      />

      <div className="ml-auto flex flex-none items-center gap-1 md:ml-0 md:gap-2.5">
        {/* On xl the test rail is pinned beside the content panel; below it,
            the same panel opens as a sheet from here. */}
        {agentShell && showTestRail && (
          <Button
            variant="outline"
            size="sm"
            onClick={agentShell.openTester}
            className="h-7 gap-1.5 rounded-md border-line bg-transparent px-2.5 text-xs text-ink-2 hover:bg-panel-2 hover:text-foreground xl:hidden"
          >
            <Bot className="h-3.5 w-3.5" />
            Test agent
          </Button>
        )}

        <SupportLink iconOnly tooltipSide="bottom" variant="ghost" className="h-10 w-10 text-ink-3 hover:text-foreground md:h-7 md:w-7" />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            {/* A 40px tap target on phones around the same 26px badge. */}
            <button
              type="button"
              aria-label="Account menu"
              className="group grid size-10 shrink-0 cursor-pointer place-items-center rounded-full outline-none md:size-[26px]"
            >
              <span className="grid size-[26px] place-items-center rounded-full border border-line bg-brand-dim font-mono text-[10px] font-semibold text-brand group-focus-visible:ring-[3px] group-focus-visible:ring-ring/60 group-focus-visible:ring-offset-1 group-focus-visible:ring-offset-background">
                {userInitials}
              </span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="bottom" align="end" className="w-56">
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col space-y-1">
                {provider === "stack" && user?.displayName && (
                  <p className="text-sm font-medium">{user.displayName}</p>
                )}
                {(user as { primaryEmail?: string } | undefined)?.primaryEmail && (
                  <p className="text-xs text-muted-foreground">
                    {(user as { primaryEmail?: string }).primaryEmail}
                  </p>
                )}
                {(user as LocalUser | undefined)?.email && (
                  <p className="text-xs text-muted-foreground">
                    {(user as LocalUser).email}
                  </p>
                )}
                {role && (
                  <p className="text-xs text-muted-foreground">Role: {ROLE_LABELS[role]}</p>
                )}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {accountLinks.map(({ href, label, icon: Icon }) => (
              <DropdownMenuItem key={href} asChild className="cursor-pointer">
                <Link href={href}>
                  <Icon className="mr-2 h-4 w-4" aria-hidden />
                  {label}
                </Link>
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem onClick={() => logout()} className="cursor-pointer">
              <LogOut className="mr-2 h-4 w-4" aria-hidden />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
