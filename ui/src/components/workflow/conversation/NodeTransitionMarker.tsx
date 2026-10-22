"use client";

import { GitBranch } from "lucide-react";

interface NodeTransitionMarkerProps {
    nodeName: string;
}

export function NodeTransitionMarker({ nodeName }: NodeTransitionMarkerProps) {
    return (
        <div className="flex items-center gap-2 py-2">
            <div className="h-px flex-1 bg-border" />
            <div className="inline-flex items-center gap-1.5 rounded-full border border-sky/20 bg-sky-dim px-3 py-1 text-xs">
                <GitBranch className="h-3 w-3 text-sky" />
                <span className="font-medium text-sky">{nodeName}</span>
            </div>
            <div className="h-px flex-1 bg-border" />
        </div>
    );
}
