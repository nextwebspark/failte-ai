import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A whole-screen message (page not found, something went wrong): a round
 * tinted icon, the screen's one h1, one plain sentence, then its actions.
 * Centred in the content panel, the same calm look as an empty state.
 */
export function FriendlyNotice({
  icon: Icon,
  title,
  children,
  actions,
  tone = "brand",
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  actions: ReactNode;
  tone?: "brand" | "danger";
}) {
  return (
    <div className="page-body flex min-h-[60vh] items-center justify-center">
      <div className="flex max-w-md flex-col items-center text-center animate-fade-up">
        <span
          aria-hidden
          className={cn(
            "grid size-14 place-items-center rounded-full",
            tone === "danger" ? "bg-danger-dim text-danger" : "bg-brand-dim text-brand",
          )}
        >
          <Icon className="size-6" />
        </span>
        <h1 className="mt-5 text-xl font-bold tracking-[-0.01em] text-foreground">{title}</h1>
        <div className="mt-2 text-[14.5px] leading-relaxed text-ink-2">{children}</div>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">{actions}</div>
      </div>
    </div>
  );
}
