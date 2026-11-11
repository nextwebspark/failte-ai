"use client";

import { Clock, Link2Off, PhoneCall } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { client } from "@/client/client.gen";
import { sharedRecordingInfoApiV1PublicRecordingTokenInfoGet } from "@/client/sdk.gen";
import type { SharedRecordingInfo } from "@/client/types.gen";
import { BrandLogo } from "@/components/BrandLogo";
import { Skeleton } from "@/components/ui/skeleton";

import { formatCallTime, formatLengthWords } from "../../usage/callsView";

type State =
    | { state: "loading" }
    | { state: "not_found" }
    | { state: "error" }
    | { state: "ready"; info: SharedRecordingInfo };

/** The recording's address: the API checks the link on every play and hands back a short-lived file link. */
export function recordingSrc(baseUrl: string, token: string): string {
    return `${baseUrl.replace(/\/+$/, "")}/api/v1/public/recording/${encodeURIComponent(token)}`;
}

const ENDED: Record<Exclude<SharedRecordingInfo["status"], "active">, { title: string; body: string }> = {
    expired: {
        title: "This link has expired",
        body: "Links to a call recording only work for a while. Ask whoever sent it for a new one.",
    },
    revoked: {
        title: "This link was turned off",
        body: "Whoever shared this recording has stopped the link. Ask them for a new one if you still need it.",
    },
    unavailable: {
        title: "This recording is no longer available",
        body: "The business no longer keeps this recording, so it can't be played.",
    },
};

/**
 * The public page behind a shared recording link: a plain player, the
 * business's name, when the call was, and when the link stops working.
 * Nothing about the caller is shown.
 */
export function SharedRecording({ token }: { token: string }) {
    const [load, setLoad] = useState<State>({ state: "loading" });

    useEffect(() => {
        let cancelled = false;
        sharedRecordingInfoApiV1PublicRecordingTokenInfoGet({ path: { token } })
            .then((response) => {
                if (cancelled) return;
                if (response.data) setLoad({ state: "ready", info: response.data });
                else setLoad(response.response?.status === 404 ? { state: "not_found" } : { state: "error" });
            })
            .catch(() => {
                if (!cancelled) setLoad({ state: "error" });
            });
        return () => {
            cancelled = true;
        };
    }, [token]);

    if (load.state === "loading") {
        return (
            <Shell>
                <span className="sr-only" role="status">Loading the recording</span>
                <Skeleton className="h-7 w-3/4" />
                <Skeleton className="mt-2 h-4 w-1/2" />
                <Skeleton className="mt-6 h-14 w-full rounded-xl" />
            </Shell>
        );
    }
    if (load.state === "not_found" || load.state === "error") {
        return (
            <Shell>
                <Ended
                    title={load.state === "error" ? "We couldn't load this recording" : "This link doesn't work"}
                    body={
                        load.state === "error"
                            ? "Something went wrong on our side. Please try again in a moment."
                            : "It may have been turned off, or the recording is no longer kept. Ask whoever sent it for a new link."
                    }
                />
            </Shell>
        );
    }

    const { info } = load;
    if (info.status !== "active") {
        return (
            <Shell>
                <Ended {...ENDED[info.status]} />
            </Shell>
        );
    }

    const zone = info.timezone ?? undefined;
    const business = info.business_name || "A business";
    return (
        <Shell>
            <p className="text-[12.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">Call recording</p>
            <h1 className="mt-1 text-2xl font-bold tracking-[-0.01em] text-foreground">A call to {business}</h1>
            <p className="mt-1 text-[14.5px] text-ink-2">
                {info.called_at ? formatCallTime(info.called_at, zone) : null}
                {typeof info.duration_seconds === "number" ? ` · ${formatLengthWords(info.duration_seconds)}` : null}
            </p>
            <div className="mt-6 rounded-xl border border-line-soft bg-panel-2 p-1.5">
                <audio
                    controls
                    preload="metadata"
                    src={recordingSrc(client.getConfig().baseUrl ?? "", token)}
                    aria-label={`Recording of a call to ${business}`}
                    className="block h-11 w-full rounded-lg [color-scheme:light] dark:[color-scheme:dark]"
                />
            </div>
            {info.expires_at && (
                <p className="mt-4 flex items-center gap-1.5 text-[13.5px] text-ink-3">
                    <Clock className="size-4 flex-none" aria-hidden />
                    This link expires on {formatCallTime(info.expires_at, zone)}.
                </p>
            )}
            <p className="mt-6 border-t border-line-soft pt-4 text-[12.5px] text-ink-3">
                Shared by {business}. Please don&apos;t pass this link on.
            </p>
        </Shell>
    );
}

function Shell({ children }: { children: ReactNode }) {
    return (
        <main className="flex min-h-dvh flex-col items-center bg-background px-4 py-10 sm:py-16">
            <div className="w-full max-w-lg">
                <div className="mb-6 flex justify-center">
                    <BrandLogo size={26} />
                </div>
                <div className="rounded-2xl border border-line bg-panel p-6 shadow-sm sm:p-8">{children}</div>
            </div>
        </main>
    );
}

function Ended({ title, body }: { title: string; body: string }) {
    return (
        <div role="status" className="flex flex-col items-start gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-panel-2 text-ink-2" aria-hidden>
                {title.includes("couldn't") ? <PhoneCall className="size-5" /> : <Link2Off className="size-5" />}
            </span>
            <h1 className="text-xl font-bold text-foreground">{title}</h1>
            <p className="text-[14.5px] text-ink-2">{body}</p>
        </div>
    );
}
