"use client";

import type { ReactNode } from "react";

import { useOwnsPageHeading } from "@/components/layout/pageHeading";
import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  /** The screen's name: the page's one h1. */
  title: ReactNode;
  /** One plain sentence on what the screen is for. */
  description?: ReactNode;
  /** Optional trailing slot (a secondary link or button). */
  action?: ReactNode;
  className?: string;
}

/**
 * The title and one-line description at the top of a screen — the same
 * header the Settings screens use. Rendering it hands the page's h1 to the
 * screen, so the app header prints its breadcrumb as plain text instead.
 */
export function PageHeader({ title, description, action, className }: PageHeaderProps) {
  useOwnsPageHeading();
  return (
    <header className={cn("mb-6 flex flex-wrap items-start justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0 max-w-2xl">
        <h1 className="text-xl font-bold tracking-[-0.01em] text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm leading-relaxed text-ink-2">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </header>
  );
}
