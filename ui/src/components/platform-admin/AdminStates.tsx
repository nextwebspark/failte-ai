import { Loader2 } from "lucide-react";

/** Loading and error lines shared by the platform admin screens. */
export function AdminLoading({ label = "Loading…" }: { label?: string }) {
    return (
        <p className="flex items-center gap-2 text-sm text-ink-3">
            <Loader2 className="h-4 w-4 animate-spin" />
            {label}
        </p>
    );
}

export function AdminError({ message }: { message: string }) {
    return (
        <div role="alert" className="rounded-lg border border-danger/30 bg-danger-dim px-4 py-3 text-sm text-danger">
            {message}
        </div>
    );
}

export function StatTile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
    return (
        <div className="rounded-lg border border-line bg-panel-2 px-4 py-3">
            <div className="font-mono text-meta uppercase tracking-[0.08em] text-ink-3">{label}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-foreground">{value}</div>
            {hint ? <div className="mt-0.5 text-xs text-ink-3">{hint}</div> : null}
        </div>
    );
}
