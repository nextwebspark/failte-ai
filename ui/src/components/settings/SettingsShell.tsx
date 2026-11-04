"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useOrgConfig } from "@/context/OrgConfigContext";
import { cn } from "@/lib/utils";

import { settingsItemFor, visibleSettingsSections } from "./settingsNav";

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

  return (
    <div className="page-body @container">
      <header className="mb-5 flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-[-0.01em] text-foreground">
          {current?.title ?? "Settings"}
        </h1>
        {current?.description && (
          <p className="text-[13.5px] text-ink-2">{current.description}</p>
        )}
      </header>

      <div className="flex flex-col gap-5 @4xl:flex-row @4xl:gap-7">
        <nav aria-label="Settings" className="shrink-0 @4xl:w-52">
          {/* Narrow: one scrolling row. Wide: grouped, sticky column. */}
          <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 @4xl:sticky @4xl:top-4 @4xl:mx-0 @4xl:flex-col @4xl:gap-4 @4xl:overflow-visible @4xl:px-0 @4xl:pb-0">
            {sections.map((section) => (
              <div key={section.label} className="flex shrink-0 gap-1 @4xl:flex-col @4xl:gap-0.5">
                <p className="hidden px-2.5 pb-1 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-3 @4xl:block">
                  {section.label}
                </p>
                {section.items.map((item) => {
                  const active = current?.url === item.url;
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.url}
                      href={item.url}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
                        "border border-line @4xl:border-transparent",
                        active
                          ? "border-transparent bg-brand-dim font-semibold text-brand"
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
        </nav>

        {/* The screen keeps its own .page-body; here the frame already pads it. */}
        <div className="min-w-0 max-w-[820px] flex-1 [&>.page-body]:max-w-none [&>.page-body]:p-0">
          {children}
        </div>
      </div>
    </div>
  );
}
