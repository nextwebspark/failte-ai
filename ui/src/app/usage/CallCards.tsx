import { ChevronRight } from "lucide-react";
import Link from "next/link";

import type { WorkflowRunUsageResponse } from "@/client/types.gen";
import { MediaPreviewButton } from "@/components/MediaPreviewDialog";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/dateTime";
import { ROW_LINK, ROW_LINK_CONTAINER } from "@/lib/rowLink";
import { cn } from "@/lib/utils";

import { formatDuration, outcomeLabel } from "./callsView";

/**
 * The calls list on a phone: one card per call instead of a wide table. The
 * number is a real link stretched over the card; the recording button sits
 * above it so it can be tapped on its own.
 */
export function CallCards({
    runs,
    timezone,
    hrefFor,
    onOpenPreview,
}: {
    runs: WorkflowRunUsageResponse[];
    timezone: string;
    hrefFor: (run: WorkflowRunUsageResponse) => string;
    onOpenPreview: (recordingUrl: string | null, transcriptUrl: string | null, runId: number) => void;
}) {
    return (
        <ul className="flex flex-col gap-2" aria-label="Calls">
            {runs.map((run) => {
                const number = run.call_type === "inbound" ? run.caller_number : run.called_number;
                return (
                    <li
                        key={run.id}
                        className={cn(
                            ROW_LINK_CONTAINER,
                            "flex items-center gap-3 rounded-lg border border-line bg-panel px-4 py-3 transition-colors hover:border-brand/50 motion-reduce:transition-none",
                        )}
                    >
                        <div className="min-w-0 flex-1">
                            <div className="flex items-baseline justify-between gap-2">
                                <Link href={hrefFor(run)} aria-label={`Open call #${run.id}`} className={ROW_LINK}>
                                    <span className={cn("font-mono text-[15px] font-semibold", !number && "font-sans text-ink-3")}>
                                        {number || "Number not known"}
                                    </span>
                                </Link>
                                <span className="flex-none font-mono text-sm tabular-nums text-ink-2">
                                    {formatDuration(run.call_duration_seconds)}
                                </span>
                            </div>
                            <div className="mt-1 text-[13px] text-ink-3">{formatDateTime(run.created_at, timezone)}</div>
                            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                                {run.disposition ? (
                                    <Badge variant="secondary">{outcomeLabel(run.disposition)}</Badge>
                                ) : (
                                    <span className="text-[13px] text-ink-3">Outcome not recorded</span>
                                )}
                                {run.workflow_name && <span className="text-[13px] text-ink-3">· {run.workflow_name}</span>}
                            </div>
                        </div>
                        <div className="relative z-10 flex-none [&>button]:size-10">
                            <MediaPreviewButton
                                recordingUrl={run.recording_url}
                                transcriptUrl={run.transcript_url}
                                runId={run.id}
                                onOpenPreview={onOpenPreview}
                            />
                        </div>
                        <ChevronRight className="size-4 flex-none text-ink-3" aria-hidden />
                    </li>
                );
            })}
        </ul>
    );
}
