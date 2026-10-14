"use client";

import { AudioLines, MessagesSquare, Star } from "lucide-react";
import type { ReactNode } from "react";

import type { PlatformModelCatalog } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
import {
    type ConfigurationSummary,
    summarizePlatformConfiguration,
    type VoiceSummary,
} from "@/lib/platformModelSummary";

export type SetupSource = "workspace" | "agent" | "legacy";

const SOURCE_LABELS: Record<SetupSource, string> = {
    workspace: "Workspace default",
    agent: "This agent's own setup",
    legacy: "Older provider setup",
};

interface CurrentSetupCardProps {
    catalog: PlatformModelCatalog;
    // The saved configuration calls run with, not the form's draft.
    configuration: unknown;
    source: SetupSource;
    // Shown underneath for comparison when the agent has its own setup.
    workspaceConfiguration?: unknown;
    dirty?: boolean;
    note?: string;
}

function VoiceTraits({ voice }: { voice: VoiceSummary }) {
    const traits = [voice.gender, voice.style && voice.tone ? `${voice.style} (${voice.tone})` : voice.style];
    return (
        <>
            <span className="font-medium">{voice.name}</span>
            {voice.recommended && (
                <Star aria-label="Recommended" className="ml-1 inline h-3 w-3 fill-current align-[-1px] text-amber-500" />
            )}
            {traits.filter(Boolean).map((trait) => (
                <span key={trait} className="text-muted-foreground"> · {trait}</span>
            ))}
        </>
    );
}

function Row({ term, children }: { term: string; children: ReactNode }) {
    return (
        <div className="flex gap-3">
            <dt className="w-14 shrink-0 text-muted-foreground">{term}</dt>
            <dd className="min-w-0">{children}</dd>
        </div>
    );
}

function SummaryBody({ summary, source }: { summary: ConfigurationSummary; source: SetupSource }) {
    if (summary.kind === "other") {
        // The badge already says it is an older setup.
        const text = source === "legacy" ? summary.text.replace(/ \(older provider setup\)$/, "") : summary.text;
        return <p className="text-sm font-medium">{text}</p>;
    }
    const Icon = summary.kind === "realtime" ? AudioLines : MessagesSquare;
    return (
        <div className="space-y-2">
            <p className="flex items-center gap-2 text-sm font-medium">
                <Icon aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                {summary.kind === "realtime" ? `${summary.mode} · ${summary.model}` : summary.mode}
            </p>
            <dl className="space-y-1 text-sm">
                {summary.kind === "realtime" ? (
                    <>
                        <Row term="Voice"><VoiceTraits voice={summary.voice} /></Row>
                        <Row term="Speaks">{summary.language}</Row>
                    </>
                ) : (
                    <>
                        <Row term="Hears">
                            {summary.stt.model}
                            <span className="text-muted-foreground"> · {summary.stt.language}</span>
                        </Row>
                        <Row term="Thinks">{summary.llm.model}</Row>
                        <Row term="Speaks">
                            <VoiceTraits voice={summary.tts.voice} />
                            <span className="text-muted-foreground">
                                {" · "}
                                {summary.tts.accent ? `${summary.tts.accent} accent` : summary.tts.language}
                                {summary.tts.speed !== 1 ? ` · ${summary.tts.speed}×` : ""}
                            </span>
                        </Row>
                    </>
                )}
            </dl>
        </div>
    );
}

/** What calls run with right now, so the form below isn't mistaken for it. */
export function CurrentSetupCard({
    catalog,
    configuration,
    source,
    workspaceConfiguration,
    dirty,
    note,
}: CurrentSetupCardProps) {
    const summary = summarizePlatformConfiguration(configuration, catalog);
    const workspace = source === "agent" && workspaceConfiguration !== undefined
        ? summarizePlatformConfiguration(workspaceConfiguration, catalog)
        : null;
    return (
        <section aria-label="Current setup" className="space-y-3 rounded-md border bg-muted/20 p-4">
            <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-medium">Current setup</h3>
                <Badge variant="outline">{SOURCE_LABELS[source]}</Badge>
                {dirty && (
                    <Badge variant="outline" className="border-amber-500/50 text-amber-600 dark:text-amber-400">
                        Unsaved changes below
                    </Badge>
                )}
            </div>
            <SummaryBody summary={summary} source={source} />
            {workspace && (
                <p className="border-t pt-2 text-xs text-muted-foreground">
                    Workspace default:{" "}
                    {workspace.kind === "other"
                        ? workspace.text
                        : workspace.kind === "realtime"
                          ? `${workspace.mode} · ${workspace.voice.name} · ${workspace.language}`
                          : `${workspace.mode} · ${workspace.tts.voice.name} · ${workspace.tts.accent ? `${workspace.tts.accent} accent` : workspace.tts.language}`}
                </p>
            )}
            {note && <p className="text-xs text-muted-foreground">{note}</p>}
        </section>
    );
}
