"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef } from "react";

import { useOwnsPageHeading } from "@/components/layout/pageHeading";
import { ScopeNote } from "@/components/layout/ScopeNote";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { cn } from "@/lib/utils";

import { settingsItemFor, settingsScopeFor, visibleSettingsSections } from "./settingsNav";

/**
 * The frame every settings screen shares: the screen's title and one-line
 * description, the grouped settings menu, then the screen itself.
 *
 * Wide, the menu is a column beside the content; narrow, it becomes one
 * scrolling row of the same links. Sized by the content panel (container
 * queries), not the window, because the app's nav panel takes part of it.
 * The screens keep their own `.page-body`; inside the frame it only lays out.
 */
export function SettingsShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { role, can } = useOrgConfig();
  const sections = visibleSettingsSections(role === null ? null : can);
  const current = settingsItemFor(pathname);
  const scope = settingsScopeFor(pathname);
  // The title below is the page's h1; the app header keeps "Settings" as text.
  useOwnsPageHeading();

  // Narrow, the menu is one scrolling row: bring the open screen's chip into
  // view (each settings route mounts its own frame, so this runs per screen).
  const activeRef = useRef<HTMLAnchorElement | null>(null);
  useEffect(() => {
    const chip = activeRef.current;
    const row = chip?.closest<HTMLElement>("[data-settings-menu]");
    if (!chip || !row || row.scrollWidth <= row.clientWidth) return;
    row.scrollLeft = chip.offsetLeft - (row.clientWidth - chip.offsetWidth) / 2;
  }, [current?.url]);

  return (
    <div className="page-body @container">
      <header className="mb-5 flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-[-0.01em] text-foreground">
          {current?.title ?? "Settings"}
        </h1>
        {current?.description && (
          <p className="text-sm leading-relaxed text-ink-2">{current.description}</p>
        )}
        {scope && <ScopeNote scope={scope} className="mt-1 self-start" />}
      </header>

      <div className="flex flex-col gap-5 @4xl:flex-row @4xl:gap-7">
        <nav aria-label="Settings" className="relative min-w-0 shrink-0 @4xl:w-52">
          {/* Narrow: one scrolling row of chips, edge to edge, with a soft fade
              at the right that says "there's more". Wide: grouped, sticky column. */}
          <div
            data-settings-menu
            className={cn(
              "-mx-4 flex snap-x scroll-px-4 gap-1.5 overflow-x-auto px-4 pb-1.5 [scrollbar-width:thin] sm:-mx-7 sm:scroll-px-7 sm:px-7",
              "@4xl:sticky @4xl:top-4 @4xl:mx-0 @4xl:snap-none @4xl:flex-col @4xl:gap-4 @4xl:overflow-visible @4xl:px-0 @4xl:pb-0",
            )}
          >
            {sections.map((section) => (
              <div
                key={section.label}
                role="group"
                aria-label={section.label}
                className="flex shrink-0 gap-1.5 @4xl:flex-col @4xl:gap-0.5"
              >
                <p
                  aria-hidden
                  className="hidden px-2.5 pb-1.5 text-meta font-semibold uppercase tracking-[0.08em] text-ink-3 @4xl:block"
                >
                  {section.label}
                </p>
                {section.items.map((item) => {
                  const active = current?.url === item.url;
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.url}
                      ref={active ? activeRef : undefined}
                      href={item.url}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-h-10 shrink-0 snap-start items-center gap-2 whitespace-nowrap rounded-full px-3.5 text-sm transition-colors",
                        "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                        "border border-line bg-panel @4xl:min-h-9 @4xl:rounded-md @4xl:border-transparent @4xl:bg-transparent @4xl:px-2.5",
                        active
                          ? "border-transparent bg-brand-dim font-semibold text-brand @4xl:bg-brand-dim"
                          : "font-medium text-ink-2 hover:bg-panel-2 hover:text-foreground",
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", active ? "text-brand" : "text-ink-3")} aria-hidden />
                      {item.title}
                    </Link>
                  );
                })}
              </div>
            ))}
          </div>
          <span
            aria-hidden
            className="pointer-events-none absolute -right-4 top-0 bottom-1.5 w-8 bg-gradient-to-l from-panel to-transparent sm:-right-7 @4xl:hidden"
          />
        </nav>

        {/* The screen keeps its own .page-body; here the frame already pads it. */}
        <div className="min-w-0 max-w-[820px] flex-1 [&>.page-body]:max-w-none [&>.page-body]:p-0">
          {children}
        </div>
      </div>
    </div>
  );
}
