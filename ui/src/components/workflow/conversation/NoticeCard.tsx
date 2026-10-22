"use client";

import { AlertTriangle, ExternalLink, MicOff } from "lucide-react";

import { cn } from "@/lib/utils";

interface NoticeCardProps {
    tone: "warning" | "error";
    title: string;
    text: string;
    linkHref?: string;
    linkLabel?: string;
}

export function NoticeCard({
    tone,
    title,
    text,
    linkHref,
    linkLabel,
}: NoticeCardProps) {
    const isWarning = tone === "warning";
    const Icon = isWarning ? MicOff : AlertTriangle;

    return (
        <div
            className={cn(
                "flex items-start gap-2 rounded-lg border px-3 py-2",
                isWarning
                    ? "border-amber/20 bg-amber-dim"
                    : "border-danger/20 bg-danger-dim",
            )}
        >
            <Icon
                className={cn(
                    "mt-0.5 h-4 w-4 shrink-0",
                    isWarning ? "text-amber" : "text-danger",
                )}
            />
            <div className="min-w-0 flex-1">
                <div
                    className={cn(
                        "text-xs font-medium",
                        isWarning ? "text-amber" : "text-danger",
                    )}
                >
                    {title}
                </div>
                <div
                    className={cn(
                        "mt-0.5 break-words text-sm",
                        isWarning ? "text-amber" : "text-danger",
                    )}
                >
                    {text}
                </div>
                {linkHref && linkLabel ? (
                    <a
                        href={linkHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={cn(
                            "mt-1 inline-flex items-center gap-1 text-xs hover:underline",
                            isWarning ? "text-amber" : "text-danger",
                        )}
                    >
                        {linkLabel} <ExternalLink className="h-3 w-3" />
                    </a>
                ) : null}
            </div>
        </div>
    );
}
