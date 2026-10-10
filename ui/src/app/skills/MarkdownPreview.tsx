import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A small, dependency-free markdown preview for skill instructions: headings,
 * paragraphs, bullet and numbered lists, fenced code, block quotes, rules,
 * plus inline `code`, **bold** and *italic*. Output is built from React
 * elements only (no HTML injection), so untrusted text is safe to show.
 */

type Block =
    | { kind: "heading"; level: number; text: string }
    | { kind: "paragraph"; text: string }
    | { kind: "list"; ordered: boolean; items: string[] }
    | { kind: "code"; text: string }
    | { kind: "quote"; text: string }
    | { kind: "rule" };

const HEADING = /^(#{1,6})[ \t]+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parseMarkdown(source: string): Block[] {
    // Every line terminator becomes \n first: `.` and `$` in the patterns
    // below must agree on where a line ends, or a line could match no branch.
    const lines = source.replace(/\r\n?|\u2028|\u2029/g, "\n").split("\n");
    const blocks: Block[] = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) {
            i += 1;
            continue;
        }
        if (line.trimStart().startsWith("```")) {
            const code: string[] = [];
            i += 1;
            while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
                code.push(lines[i]);
                i += 1;
            }
            i += 1; // closing fence (or end of input)
            blocks.push({ kind: "code", text: code.join("\n") });
            continue;
        }
        const heading = HEADING.exec(line);
        if (heading) {
            blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
            i += 1;
            continue;
        }
        if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
            blocks.push({ kind: "rule" });
            i += 1;
            continue;
        }
        if (line.trimStart().startsWith(">")) {
            const quote: string[] = [];
            while (i < lines.length && lines[i].trimStart().startsWith(">")) {
                quote.push(lines[i].trimStart().replace(/^>\s?/, ""));
                i += 1;
            }
            blocks.push({ kind: "quote", text: quote.join(" ") });
            continue;
        }
        const listPattern = BULLET.test(line) ? BULLET : NUMBERED.test(line) ? NUMBERED : null;
        if (listPattern) {
            const items: string[] = [];
            while (i < lines.length && lines[i].trim()) {
                const match = listPattern.exec(lines[i]);
                if (match) items.push(match[1]);
                else if (items.length > 0) items[items.length - 1] += ` ${lines[i].trim()}`;
                i += 1;
            }
            blocks.push({ kind: "list", ordered: listPattern === NUMBERED, items });
            continue;
        }
        // The first line is always consumed, so the loop always makes progress.
        const paragraph: string[] = [line.trim()];
        i += 1;
        while (
            i < lines.length &&
            lines[i].trim() &&
            !HEADING.test(lines[i]) &&
            !lines[i].trimStart().startsWith("```") &&
            !lines[i].trimStart().startsWith(">") &&
            !BULLET.test(lines[i]) &&
            !NUMBERED.test(lines[i])
        ) {
            paragraph.push(lines[i].trim());
            i += 1;
        }
        blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    }
    return blocks;
}

/** Inline `code`, **bold** and *italic*; everything else is plain text. */
function renderInline(text: string): ReactNode[] {
    const parts: ReactNode[] = [];
    const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)/g;
    let last = 0;
    let key = 0;
    for (const match of text.matchAll(pattern)) {
        const index = match.index ?? 0;
        if (index > last) parts.push(text.slice(last, index));
        const token = match[0];
        if (token.startsWith("`")) {
            parts.push(
                <code key={key++} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
                    {token.slice(1, -1)}
                </code>,
            );
        } else if (token.startsWith("**")) {
            parts.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
        } else {
            parts.push(<em key={key++}>{token.slice(1, -1)}</em>);
        }
        last = index + token.length;
    }
    if (last < text.length) parts.push(text.slice(last));
    return parts;
}

const HEADING_CLASS: Record<number, string> = {
    1: "text-lg font-semibold",
    2: "text-base font-semibold",
    3: "text-sm font-semibold",
};

export function MarkdownPreview({ source, className }: { source: string; className?: string }) {
    const blocks = parseMarkdown(source);
    if (blocks.length === 0) {
        return <p className={cn("text-sm text-muted-foreground", className)}>Nothing to preview yet.</p>;
    }
    return (
        <div className={cn("space-y-3 text-sm leading-relaxed break-words", className)}>
            {blocks.map((block, index) => {
                switch (block.kind) {
                    case "heading": {
                        const Tag = (`h${Math.min(block.level + 2, 6)}` as "h3" | "h4" | "h5" | "h6");
                        return (
                            <Tag key={index} className={HEADING_CLASS[block.level] ?? "text-sm font-semibold"}>
                                {renderInline(block.text)}
                            </Tag>
                        );
                    }
                    case "paragraph":
                        return <p key={index}>{renderInline(block.text)}</p>;
                    case "list": {
                        const ListTag = block.ordered ? "ol" : "ul";
                        return (
                            <ListTag
                                key={index}
                                className={cn("space-y-1 pl-5", block.ordered ? "list-decimal" : "list-disc")}
                            >
                                {block.items.map((item, itemIndex) => (
                                    <li key={itemIndex}>{renderInline(item)}</li>
                                ))}
                            </ListTag>
                        );
                    }
                    case "code":
                        return (
                            <pre
                                key={index}
                                className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed"
                            >
                                {block.text}
                            </pre>
                        );
                    case "quote":
                        return (
                            <blockquote key={index} className="border-l-2 border-line pl-3 text-ink-2">
                                {renderInline(block.text)}
                            </blockquote>
                        );
                    case "rule":
                        return <hr key={index} className="border-line-soft" />;
                    default:
                        return <Fragment key={index} />;
                }
            })}
        </div>
    );
}
