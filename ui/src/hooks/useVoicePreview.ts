import { useCallback, useEffect, useRef, useState } from "react";

import { resolveBrowserBackendUrl } from "@/lib/apiClient";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";

/**
 * Plays one voice preview at a time.
 *
 * Catalogue providers served by MPS ship absolute, public sample URLs. Ours
 * (Google) are relative paths on our own API, which need the backend origin
 * AND a bearer token; an <audio> element can send neither, so those bytes are
 * fetched and played from a blob URL instead.
 */
export function useVoicePreview() {
    const { getAccessToken } = useAuth();
    const [playingId, setPlayingId] = useState<string | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    // Blob URL for the preview currently playing, if we fetched the bytes
    // ourselves. Held so it can be revoked: a blob lives until it is.
    const blobUrlRef = useRef<string | null>(null);
    // Discards a preview fetch that finishes after the user has moved on:
    // clicked another voice, stopped playback, or closed the picker.
    const previewRequestId = useRef(0);

    const releaseBlob = useCallback(() => {
        if (blobUrlRef.current) {
            URL.revokeObjectURL(blobUrlRef.current);
            blobUrlRef.current = null;
        }
    }, []);

    const stop = useCallback(() => {
        previewRequestId.current++;
        if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
        }
        releaseBlob();
        setPlayingId(null);
    }, [releaseBlob]);

    useEffect(() => stop, [stop]);

    /** Play *url* as voice *id*, or stop it if it is already playing. */
    const toggle = useCallback(
        async (id: string, url: string | null | undefined) => {
            setPreviewError(null);
            if (playingId === id) {
                stop();
                return;
            }
            stop();
            if (!url) return;

            const previewId = ++previewRequestId.current;
            let src = url;
            if (src.startsWith("/")) {
                try {
                    const token = await getAccessToken();
                    const response = await fetch(`${resolveBrowserBackendUrl()}${src}`, {
                        headers: { Authorization: `Bearer ${token}` },
                    });
                    if (!response.ok) throw new Error(`preview ${response.status}`);
                    const blobUrl = URL.createObjectURL(await response.blob());
                    if (previewId !== previewRequestId.current) {
                        URL.revokeObjectURL(blobUrl);
                        return;
                    }
                    src = blobUrl;
                    blobUrlRef.current = src;
                } catch (err) {
                    logger.error(`Voice preview failed for ${id}: ${err}`);
                    if (previewId === previewRequestId.current) {
                        setPreviewError("Preview unavailable for this voice");
                        setPlayingId(null);
                    }
                    return;
                }
            }
            if (previewId !== previewRequestId.current) return;

            const audio = new Audio(src);
            audioRef.current = audio;
            setPlayingId(id);
            const clear = () => {
                if (audioRef.current === audio) audioRef.current = null;
                if (blobUrlRef.current === src) releaseBlob();
                setPlayingId((current) => (current === id ? null : current));
            };
            audio.onended = clear;
            audio.onerror = clear;
            audio.play().catch(clear);
        },
        [getAccessToken, playingId, releaseBlob, stop],
    );

    return { playingId, previewError, toggle, stop } as const;
}
