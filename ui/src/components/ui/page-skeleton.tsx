import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Placeholders shaped like the screens they stand in for, so nothing jumps
 * when the real content arrives. Used by the routes' loading.tsx files and by
 * the shell while it waits for your role.
 *
 *   cards     a header, then a two-column grid of cards (Overview, Integrations)
 *   list      a header, then one card of rows (Calls, Tools, Files)
 *   settings  stacked settings cards (inside the Settings frame)
 *   detail    a header, then a tall form card (a single item)
 */
export type PageSkeletonVariant = "cards" | "list" | "settings" | "detail";

function HeaderSkeleton() {
  return (
    <div className="mb-6 space-y-2">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-4 w-80 max-w-full" />
    </div>
  );
}

function RowsSkeleton({ rows }: { rows: number }) {
  return (
    <div className="divide-y divide-line-soft">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-[18px] py-3.5">
          <Skeleton className="size-8 shrink-0 rounded-lg" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="hidden h-8 w-20 sm:block" />
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton({
  variant = "list",
  withHeader = true,
  className,
}: {
  variant?: PageSkeletonVariant;
  /** Leave the title placeholder out when the frame already shows one. */
  withHeader?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading"
      className={cn("page-body", className)}
    >
      <span className="sr-only">Loading…</span>
      {withHeader && variant !== "settings" && <HeaderSkeleton />}

      {variant === "cards" && (
        <div className="grid max-w-4xl grid-cols-1 gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex items-start gap-3.5 rounded-lg border border-line bg-panel px-[18px] py-4">
              <Skeleton className="size-10 shrink-0 rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </div>
          ))}
        </div>
      )}

      {variant === "list" && (
        <div className="overflow-hidden rounded-lg border border-line bg-panel">
          <div className="border-b border-line-soft px-[18px] py-3.5">
            <Skeleton className="h-9 w-full max-w-md" />
          </div>
          <RowsSkeleton rows={5} />
        </div>
      )}

      {variant === "settings" && (
        <div className="flex flex-col gap-[18px]">
          {[3, 2].map((rows, i) => (
            <div key={i} className="overflow-hidden rounded-lg border border-line bg-panel">
              <div className="flex items-center gap-2.5 border-b border-line-soft px-[18px] py-3.5">
                <Skeleton className="size-7 rounded-md" />
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-36" />
                  <Skeleton className="h-3 w-56 max-w-full" />
                </div>
              </div>
              <RowsSkeleton rows={rows} />
            </div>
          ))}
        </div>
      )}

      {variant === "detail" && (
        <div className="max-w-4xl space-y-4 rounded-lg border border-line bg-panel px-[18px] py-5">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
