import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function CardSkeleton({ rows, className }: { rows: number; className?: string }) {
    return (
        <div className={cn("rounded-[14px] border border-line bg-panel px-[18px] py-4", className)}>
            <Skeleton className="h-4 w-40" />
            <div className="mt-4 flex flex-col gap-3">
                {Array.from({ length: rows }, (_, i) => (
                    <div key={i} className="flex items-center gap-3">
                        <Skeleton className="h-9 w-1 rounded" />
                        <div className="flex-1 space-y-1.5">
                            <Skeleton className="h-3.5 w-1/2" />
                            <Skeleton className="h-3 w-3/4" />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Home while it loads: shaped like the tiles and cards, so nothing jumps. */
export function HomeSkeleton({ withHeader = true }: { withHeader?: boolean }) {
    const body = (
        <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
                {Array.from({ length: 4 }, (_, i) => (
                    <div key={i} className="space-y-2.5 rounded-[14px] border border-line bg-panel px-[18px] py-4">
                        <div className="flex items-center gap-2">
                            <Skeleton className="size-7 rounded-lg" />
                            <Skeleton className="h-3.5 w-24" />
                        </div>
                        <Skeleton className="h-8 w-14" />
                        <Skeleton className="h-3 w-3/4" />
                    </div>
                ))}
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
                <CardSkeleton rows={3} />
                <CardSkeleton rows={3} />
            </div>
        </>
    );
    if (!withHeader) {
        return (
            <div role="status" aria-label="Loading" className="flex flex-col gap-5">
                {body}
            </div>
        );
    }
    return (
        <div role="status" aria-label="Loading" className="page-body flex flex-col gap-5">
            <span className="sr-only">Loading…</span>
            <div className="space-y-2">
                <Skeleton className="h-7 w-64" />
                <Skeleton className="h-4 w-80 max-w-full" />
            </div>
            {body}
        </div>
    );
}
