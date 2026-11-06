import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

/** "21–40 of 135" with previous/next buttons. */
export function Pager({
    page,
    limit,
    total,
    onPage,
}: {
    page: number;
    limit: number;
    total: number;
    onPage: (page: number) => void;
}) {
    const first = total === 0 ? 0 : (page - 1) * limit + 1;
    const last = Math.min(page * limit, total);
    return (
        <div className="flex items-center justify-between gap-3 text-xs text-ink-3">
            <span className="tabular-nums">
                {first}–{last} of {total}
            </span>
            <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
                    <ChevronLeft className="h-3.5 w-3.5" />
                    Previous
                </Button>
                <Button variant="outline" size="sm" disabled={last >= total} onClick={() => onPage(page + 1)}>
                    Next
                    <ChevronRight className="h-3.5 w-3.5" />
                </Button>
            </div>
        </div>
    );
}
