import { cn } from "@/lib/utils";

export type DiffLineKind = "file" | "hunk" | "added" | "removed" | "context";

export interface DiffLine {
    kind: DiffLineKind;
    text: string;
}

/** Classifies each line of a unified diff for display. */
export function parseUnifiedDiff(diff: string): DiffLine[] {
    if (!diff.trim()) return [];
    return diff
        .replace(/\n$/, "")
        .split("\n")
        .map((text): DiffLine => {
            if (text.startsWith("+++") || text.startsWith("---")) return { kind: "file", text };
            if (text.startsWith("@@")) return { kind: "hunk", text };
            if (text.startsWith("+")) return { kind: "added", text };
            if (text.startsWith("-")) return { kind: "removed", text };
            return { kind: "context", text };
        });
}

const LINE_CLASS: Record<DiffLineKind, string> = {
    file: "font-semibold text-foreground",
    hunk: "bg-sky-dim text-sky",
    added: "bg-ok-dim text-ok",
    removed: "bg-danger-dim text-danger",
    context: "text-ink-2",
};

const LINE_LABEL: Partial<Record<DiffLineKind, string>> = {
    added: "Added: ",
    removed: "Removed: ",
};

/** A unified diff, colour-coded, with screen-reader labels for changed lines. */
export function DiffView({ diff, className }: { diff: string; className?: string }) {
    const lines = parseUnifiedDiff(diff);
    if (lines.length === 0) {
        return <p className="text-sm text-muted-foreground">No differences.</p>;
    }
    return (
        <pre
            className={cn(
                "max-h-[50vh] overflow-auto rounded-md border border-line bg-panel-2 py-2 font-mono text-xs leading-relaxed",
                className,
            )}
            aria-label="Changes from your copy to the library version"
        >
            {lines.map((line, index) => (
                <div key={index} className={cn("whitespace-pre-wrap break-all px-3", LINE_CLASS[line.kind])}>
                    {LINE_LABEL[line.kind] && <span className="sr-only">{LINE_LABEL[line.kind]}</span>}
                    {line.text || " "}
                </div>
            ))}
        </pre>
    );
}
