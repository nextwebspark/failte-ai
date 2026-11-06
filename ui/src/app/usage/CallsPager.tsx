import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

import { pageList } from "./callsView";

const PAGE_BUTTON =
    "grid h-10 min-w-10 place-items-center rounded-lg border px-2 text-sm font-semibold tabular-nums outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-40 motion-reduce:transition-none sm:h-8 sm:min-w-8";

/** "Showing 1–10 of 312 calls", always, and the page buttons when there is more than one page. */
export function CallsPager({ page, pageSize, total, onPage }: {
    page: number;
    pageSize: number;
    total: number;
    onPage: (page: number) => void;
}) {
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const last = Math.min(total, page * pageSize);
    return (
        <nav
            aria-label="Pages of calls"
            className="flex flex-wrap items-center justify-between gap-3 border-t border-line-soft px-4 py-3"
        >
            <p className="text-sm text-ink-3" aria-live="polite">
                Showing{" "}
                <b className="font-semibold text-foreground">
                    {first.toLocaleString("en-IE")}–{last.toLocaleString("en-IE")}
                </b>{" "}
                of <b className="font-semibold text-foreground">{total.toLocaleString("en-IE")}</b>{" "}
                {total === 1 ? "call" : "calls"}
            </p>
            {pages > 1 && (
                <div className="flex items-center gap-1">
                    <button
                        type="button"
                        className={cn(PAGE_BUTTON, "border-line bg-panel text-ink-2 hover:text-foreground")}
                        onClick={() => onPage(page - 1)}
                        disabled={page <= 1}
                        aria-label="Previous page"
                    >
                        <ChevronLeft className="size-4" aria-hidden />
                    </button>
                    {/* Every page number on a computer; just "3 of 32" on a phone. */}
                    <span className="px-2 text-sm text-ink-3 sm:hidden">
                        {page} of {pages}
                    </span>
                    {pageList(page, pages).map((item, index) =>
                        item === "gap" ? (
                            <span key={`gap-${index}`} className="hidden px-1 text-ink-3 sm:inline" aria-hidden>
                                …
                            </span>
                        ) : (
                            <button
                                key={item}
                                type="button"
                                onClick={() => onPage(item)}
                                aria-current={item === page ? "page" : undefined}
                                aria-label={`Page ${item}`}
                                className={cn(
                                    PAGE_BUTTON,
                                    "hidden sm:grid",
                                    item === page
                                        ? "border-foreground bg-foreground text-background"
                                        : "border-transparent text-ink-2 hover:bg-panel-2 hover:text-foreground",
                                )}
                            >
                                {item}
                            </button>
                        ),
                    )}
                    <button
                        type="button"
                        className={cn(PAGE_BUTTON, "border-line bg-panel text-ink-2 hover:text-foreground")}
                        onClick={() => onPage(page + 1)}
                        disabled={page >= pages}
                        aria-label="Next page"
                    >
                        <ChevronRight className="size-4" aria-hidden />
                    </button>
                </div>
            )}
        </nav>
    );
}
