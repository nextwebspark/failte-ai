"use client";

import Link from "next/link";
import React from "react";

/**
 * The few bits of markdown a help answer uses: paragraphs, numbered and
 * bulleted lists, **bold** and [links](/path). Built as React nodes, never
 * as HTML, so nothing in an answer can inject markup. The API has already
 * reduced links to in-app screens and the website contact form; anything
 * else that slips through renders as plain text.
 */

const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

export function isSafeHref(href: string): boolean {
  return (href.startsWith("/") && !href.startsWith("//")) || href.startsWith("https://lightmove.ai/");
}

function inline(text: string, onNavigate: () => void, keyPrefix: string): React.ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    const bold = /^\*\*([^*]+)\*\*$/.exec(part);
    if (bold) return <strong key={key} className="font-semibold text-foreground">{bold[1]}</strong>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link;
      if (!isSafeHref(href)) return <React.Fragment key={key}>{label}</React.Fragment>;
      const className = "font-medium text-brand underline underline-offset-2 hover:no-underline";
      return href.startsWith("/") ? (
        <Link key={key} href={href} onClick={onNavigate} className={className}>
          {label}
        </Link>
      ) : (
        <a key={key} href={href} target="_blank" rel="noopener noreferrer" className={className}>
          {label}
        </a>
      );
    }
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

type Block = { kind: "p"; lines: string[] } | { kind: "ol" | "ul"; items: string[] };

export function blocksOf(markdown: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of markdown.split("\n")) {
    const line = raw.trimEnd();
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const last = blocks[blocks.length - 1];
    if (ordered || bullet) {
      const kind = ordered ? "ol" : "ul";
      const item = (ordered ?? bullet)![1];
      if (last && last.kind === kind) last.items.push(item);
      else blocks.push({ kind, items: [item] });
    } else if (!line.trim()) {
      if (last && last.kind === "p" && last.lines.length) blocks.push({ kind: "p", lines: [] });
    } else if (last && last.kind === "p") {
      last.lines.push(line.replace(/^#+\s*/, ""));
    } else {
      blocks.push({ kind: "p", lines: [line.replace(/^#+\s*/, "")] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : b.items.length > 0));
}

export function HelpMarkdown({ text, onNavigate }: { text: string; onNavigate: () => void }) {
  return (
    <div className="space-y-2 text-body text-foreground">
      {blocksOf(text).map((block, i) => {
        if (block.kind === "p") {
          return <p key={i}>{inline(block.lines.join(" "), onNavigate, `p${i}`)}</p>;
        }
        const List = block.kind;
        return (
          <List key={i} className={List === "ol" ? "list-decimal space-y-1 pl-5" : "list-disc space-y-1 pl-5"}>
            {block.items.map((item, j) => (
              <li key={j}>{inline(item, onNavigate, `l${i}-${j}`)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
