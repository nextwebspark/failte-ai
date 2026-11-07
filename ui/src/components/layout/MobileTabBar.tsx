"use client";

import {
  Bot,
  ChevronDown,
  CircleHelp,
  Home,
  ListChecks,
  LogOut,
  type LucideIcon,
  Menu,
  Moon,
  Phone,
  Sun,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import React, { useEffect, useRef, useState } from "react";

import { SUPPORT_MAILTO } from "@/components/SupportLink";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { cn } from "@/lib/utils";
import { workspaceDisplayName } from "@/lib/workspaceName";

import { isAgentRoute } from "./agentNav";
import { initialsOf, memberName } from "./memberIdentity";
import { FOLLOW_UPS_URL } from "./navConfig";
import { useShellChrome } from "./shellContext";
import { type ResolvedNavItem, useWorkspaceNav } from "./useWorkspaceNav";

/**
 * Below md the sidebar gives way to the phone layout from the redesign
 * (mocks/mobile.png, mobile-more.png): a fixed tab bar with the four places
 * an owner checks between customers, and More, a sheet from the bottom with
 * everything else. The full-screen builder (the conversation diagram) hides it.
 */

/** Height of the bar, without the safe area under it. */
export const TAB_BAR_HEIGHT = 64;

/** `/workflow/12` exactly: the conversation diagram, which needs the whole screen. */
export function hidesTabBar(pathname: string): boolean {
  return /^\/workflow\/\d+\/?$/.test(pathname);
}

type Tab = { key: string; title: string; href: string; icon: LucideIcon; isActive: boolean; badge?: number };

function TabLink({ tab, onNavigate }: { tab: Tab; onNavigate: () => void }) {
  const Icon = tab.icon;
  const count = tab.badge && tab.badge > 0 ? tab.badge : 0;
  return (
    <Link
      href={tab.href}
      onClick={onNavigate}
      aria-current={tab.isActive ? "page" : undefined}
      className={cn(
        "relative flex min-h-11 min-w-0 flex-col items-center justify-center gap-[3px] rounded-lg text-meta font-semibold outline-none",
        "focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/50",
        tab.isActive ? "text-brand" : "text-ink-3"
      )}
    >
      <span className="relative">
        <Icon className="size-[21px]" strokeWidth={1.9} aria-hidden />
        {count > 0 && (
          <span className="absolute -right-2.5 -top-1.5 grid min-w-4 place-items-center rounded-full bg-amber px-1 text-[10px] font-bold leading-4 text-white">
            {count}
            <span className="sr-only"> open</span>
          </span>
        )}
      </span>
      <span className="max-w-full truncate px-0.5">{tab.title}</span>
    </Link>
  );
}

function SheetRow({
  href,
  icon: Icon,
  title,
  aside,
  onNavigate,
  isActive,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  aside?: React.ReactNode;
  onNavigate: () => void;
  isActive?: boolean;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "flex min-h-12 items-center gap-3 rounded-[10px] px-1.5 text-[15px] font-medium text-foreground outline-none",
        "hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50",
        isActive && "bg-brand-dim text-brand"
      )}
    >
      <Icon className={cn("size-5 shrink-0 text-ink-2", isActive && "text-brand")} />
      <span className="min-w-0 flex-1 truncate">{title}</span>
      {aside}
    </Link>
  );
}

function SheetLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-1.5 pb-1 pt-2.5 text-meta font-semibold uppercase tracking-[0.06em] text-ink-3">{children}</p>
  );
}

export function MobileTabBar() {
  const pathname = usePathname();
  const { workspaceMode } = useShellChrome();
  const sections = useWorkspaceNav();
  const { role, orgContext } = useOrgConfig();
  const { user, logout } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const [moreOpen, setMoreOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Any move to another screen closes the sheet (links, Back, Forward).
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!moreOpen) setAdvancedOpen(false);
  }, [moreOpen]);

  const items = sections.flatMap((s) => s.items);
  const byUrl = (url: string) => items.find((item) => item.url === url && !item.agentRow);
  const agentFacts = items.find((item) => item.agentRow === "facts");
  const phone = items.find((item) => item.agentRow === "phone");
  const settings = items.find((item) => item.settingsHub);
  const advanced = sections.find((s) => s.collapsible)?.items ?? [];

  const onAgentScreen = isAgentRoute(pathname) && !workspaceMode;
  const home = byUrl("/overview");
  const calls = byUrl("/usage");
  const followUps = byUrl(FOLLOW_UPS_URL);

  const tabs: Tab[] = [];
  if (home) tabs.push({ key: "home", title: "Home", href: home.href, icon: Home, isActive: home.isActive });
  if (calls) tabs.push({ key: "calls", title: "Calls", href: calls.href, icon: Phone, isActive: calls.isActive });
  if (followUps) {
    tabs.push({
      key: "follow-ups",
      title: "Follow-ups",
      href: followUps.href,
      icon: ListChecks,
      isActive: followUps.isActive,
      badge: followUps.badge,
    });
  }
  if (agentFacts) {
    tabs.push({
      key: "agent",
      title: "Your agent",
      href: agentFacts.href,
      icon: Bot,
      // Every screen of an agent belongs to this tab, and so does creating one.
      isActive: onAgentScreen || pathname === agentFacts.href.split("#")[0],
    });
  }

  const moreItems: ResolvedNavItem[] = [byUrl("/bookings"), byUrl("/reports")].filter(
    (item): item is ResolvedNavItem => Boolean(item),
  );
  const tabActive = tabs.some((tab) => tab.isActive);
  const moreActive = moreOpen || (!tabActive && [...moreItems, phone, settings, ...advanced].some((i) => i?.isActive));

  // A row that leads to another screen hands focus to that screen, not back
  // to More (AppLayout's route-change focus does the rest).
  const navigated = useRef(false);
  const close = () => {
    navigated.current = true;
    setMoreOpen(false);
  };
  const workspaceName = workspaceDisplayName(orgContext?.organization_name);
  const person = memberName(user);
  const isDark = resolvedTheme === "dark";

  return (
    <>
      <nav
        aria-label="Main"
        data-mobile-tab-bar
        className={cn(
          "fixed inset-x-0 bottom-0 border-t border-line bg-panel pb-[env(safe-area-inset-bottom)] md:hidden",
          // Above the More sheet's backdrop while it is open (as in the mock);
          // otherwise under every dialog and sheet a screen opens.
          moreOpen ? "z-[60]" : "z-40"
        )}
      >
        <div
          className="grid px-1"
          style={{ gridTemplateColumns: `repeat(${tabs.length + 1}, minmax(0, 1fr))`, height: TAB_BAR_HEIGHT }}
        >
          {tabs.map((tab) => (
            <TabLink key={tab.key} tab={tab} onNavigate={close} />
          ))}
          <button
            type="button"
            onClick={() => setMoreOpen((open) => !open)}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            className={cn(
              "relative flex min-h-11 min-w-0 flex-col items-center justify-center gap-[3px] rounded-lg text-meta font-semibold outline-none",
              "focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/50",
              moreActive ? "text-brand" : "text-ink-3"
            )}
          >
            <Menu className="size-[21px]" strokeWidth={1.9} aria-hidden />
            More
          </button>
        </div>
      </nav>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent
          side="bottom"
          onOpenAutoFocus={() => {
            navigated.current = false;
          }}
          onCloseAutoFocus={(event) => {
            if (!navigated.current) return;
            event.preventDefault();
            // AppLayout's MAIN_CONTENT_ID (not imported: AppLayout imports this file).
            document.getElementById("main-content")?.focus({ preventScroll: true });
          }}
          // Sits on the tab bar, as in the mock; the bar stays visible below it.
          style={{ bottom: `calc(${TAB_BAR_HEIGHT}px + env(safe-area-inset-bottom))` }}
          className="max-h-[calc(100svh-120px)] gap-0 overflow-y-auto rounded-t-[18px] border-t-0 bg-panel px-3.5 pb-3 pt-2.5 md:hidden"
        >
          <div aria-hidden className="mx-auto mb-3 h-1 w-[38px] shrink-0 rounded bg-line" />
          <SheetTitle className="sr-only">More</SheetTitle>
          <SheetDescription className="sr-only">Everything that isn&apos;t in the tab bar.</SheetDescription>

          <div className="mb-2 flex items-center gap-2.5 rounded-[10px] border border-line px-2.5 py-2 pr-10">
            <span
              aria-hidden
              className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-brand-dim text-[12px] font-bold text-brand"
            >
              {initialsOf(workspaceName, "W")}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">{workspaceName}</p>
              <p className="truncate text-[12px] text-ink-3">
                {[person, role ? ROLE_LABELS[role] : null].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>

          {moreItems.map((item) => (
            <SheetRow key={item.url} href={item.href} icon={item.icon} title={item.title} onNavigate={close} isActive={item.isActive} />
          ))}

          {(phone || settings || advanced.length > 0) && <SheetLabel>Your agent</SheetLabel>}
          {phone && <SheetRow href={phone.href} icon={phone.icon} title={phone.title} onNavigate={close} isActive={phone.isActive} />}
          {settings && (
            <SheetRow href={settings.href} icon={settings.icon} title={settings.title} onNavigate={close} isActive={settings.isActive} />
          )}
          {advanced.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setAdvancedOpen((open) => !open)}
                aria-expanded={advancedOpen}
                aria-controls="more-advanced"
                className="flex min-h-12 w-full items-center gap-3 rounded-[10px] px-1.5 text-left text-[15px] font-medium text-foreground outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <Wrench className="size-5 shrink-0 text-ink-2" aria-hidden />
                <span className="min-w-0 flex-1 truncate">Advanced setup</span>
                <span className="text-caption font-medium text-ink-3">Best on a computer</span>
                <ChevronDown
                  aria-hidden
                  className={cn("size-4 shrink-0 text-ink-3 transition-transform motion-reduce:transition-none", advancedOpen && "rotate-180")}
                />
              </button>
              {advancedOpen && (
                <div id="more-advanced" className="ml-4 border-l border-line-soft pl-2">
                  {advanced.map((item) => (
                    <SheetRow key={item.url} href={item.href} icon={item.icon} title={item.title} onNavigate={close} isActive={item.isActive} />
                  ))}
                </div>
              )}
            </>
          )}

          <SheetLabel>Account</SheetLabel>
          <a
            href={SUPPORT_MAILTO}
            className="flex min-h-12 items-center gap-3 rounded-[10px] px-1.5 text-[15px] font-medium text-foreground outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <CircleHelp className="size-5 shrink-0 text-ink-2" aria-hidden />
            Help
            <span className="ml-auto text-caption font-medium text-ink-3">Email us</span>
          </a>
          <button
            type="button"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            className="flex min-h-12 w-full items-center gap-3 rounded-[10px] px-1.5 text-left text-[15px] font-medium text-foreground outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            {isDark ? (
              <Sun className="size-5 shrink-0 text-ink-2" aria-hidden />
            ) : (
              <Moon className="size-5 shrink-0 text-ink-2" aria-hidden />
            )}
            {isDark ? "Light mode" : "Dark mode"}
          </button>
          <button
            type="button"
            onClick={() => {
              close();
              void logout();
            }}
            className="flex min-h-12 w-full items-center gap-3 rounded-[10px] px-1.5 text-left text-[15px] font-medium text-foreground outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <LogOut className="size-5 shrink-0 text-ink-2" aria-hidden />
            Sign out
          </button>
        </SheetContent>
      </Sheet>
    </>
  );
}
