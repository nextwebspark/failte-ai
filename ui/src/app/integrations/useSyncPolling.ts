"use client";

import { useEffect, useState } from "react";

/** How often connections are reloaded while a sync runs. */
export const SYNC_POLL_MS = 4000;
/** Polling stops after this long; the page then asks for a manual refresh. */
export const SYNC_POLL_LIMIT_MS = 10 * 60 * 1000;

/**
 * While `active`, calls `reload` every `intervalMs`: each call is scheduled
 * only after the previous one finished, never while the tab is hidden, and
 * not at all after `limitMs`. Returns true once polling gave up.
 */
export function useSyncPolling(
    active: boolean,
    reload: () => Promise<unknown>,
    { intervalMs = SYNC_POLL_MS, limitMs = SYNC_POLL_LIMIT_MS } = {},
): boolean {
    const [gaveUp, setGaveUp] = useState(false);

    useEffect(() => {
        if (!active) {
            setGaveUp(false);
            return;
        }
        let stopped = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const deadline = Date.now() + limitMs;

        const schedule = () => {
            if (stopped) return;
            if (Date.now() >= deadline) {
                setGaveUp(true);
                return;
            }
            timer = setTimeout(tick, intervalMs);
        };
        const tick = async () => {
            if (stopped) return;
            if (typeof document === "undefined" || !document.hidden) {
                try {
                    await reload();
                } catch {
                    // a failed poll is retried on the next tick
                }
            }
            schedule();
        };

        schedule();
        return () => {
            stopped = true;
            if (timer !== undefined) clearTimeout(timer);
        };
    }, [active, reload, intervalMs, limitMs]);

    return gaveUp;
}
