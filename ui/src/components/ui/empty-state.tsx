import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  icon: LucideIcon;
  /** One short, bold line: what's missing. */
  title: ReactNode;
  /** One helpful sentence: what to do about it. */
  description?: ReactNode;
  /** Ideally one button or link. */
  action?: ReactNode;
  /** Use "danger" for a friendly error with a "Try again" action. */
  tone?: "brand" | "danger";
  /** Make the title a heading when the state is the whole screen (e.g. "not found"). */
  titleAs?: "p" | "h1" | "h2" | "h3";
  className?: string;
}

/**
 * The empty state from Calls: a round tinted icon, a bold one-line title, one
 * helpful sentence and, ideally, one action.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  tone = "brand",
  titleAs: Title = "p",
  className,
}: EmptyStateProps) {
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={cn("flex flex-col items-center gap-2 px-4 py-12 text-center", className)}
    >
      <span
        className={cn(
          "grid size-11 place-items-center rounded-full",
          tone === "danger" ? "bg-danger-dim text-danger" : "bg-brand-dim text-brand",
        )}
        aria-hidden
      >
        <Icon className="size-5" />
      </span>
      <Title className="text-base font-medium text-foreground">{title}</Title>
      {description && <p className="max-w-sm text-sm text-ink-3">{description}</p>}
      {action && <div className="mt-2 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  );
}
