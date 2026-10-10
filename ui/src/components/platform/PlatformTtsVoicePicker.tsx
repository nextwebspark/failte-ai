"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { getVoicesApiV1UserConfigurationsVoicesProviderGet } from "@/client/sdk.gen";
import type { GetVoicesApiV1UserConfigurationsVoicesProviderGetData, PlatformCatalogOption } from "@/client/types.gen";
import { type VoiceCardOption, VoiceCardPicker } from "@/components/platform/VoiceCardPicker";
import logger from "@/lib/logger";

type VoicesProvider = GetVoicesApiV1UserConfigurationsVoicesProviderGetData["path"]["provider"];

interface PlatformTtsVoicePickerProps {
    // Provider id for the voice catalog endpoint (catalog `voice_catalog`).
    catalog: string;
    model: string;
    language: string;
    value: string;
    onChange: (voice: string) => void;
    disabled?: boolean;
    labelledBy?: string;
    // Speaking styles and the recommended shortlist by voice name ("Kore" →
    // "Firm"); Chirp 3 HD and Gemini Live share their voices.
    styles?: PlatformCatalogOption[];
}

/**
 * The text-to-speech voices for the selected voice language, as the same
 * cards the speech-to-speech voices use.
 */
export function PlatformTtsVoicePicker({
    catalog,
    model,
    language,
    value,
    onChange,
    disabled,
    labelledBy,
    styles = [],
}: PlatformTtsVoicePickerProps) {
    const [voices, setVoices] = useState<VoiceCardOption[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;
        setVoices(null);
        setError(null);
        const [base, region] = language.split("-");
        (async () => {
            try {
                const response = await getVoicesApiV1UserConfigurationsVoicesProviderGet({
                    path: { provider: catalog as VoicesProvider },
                    query: { model, language: base.toLowerCase(), ...(region ? { accent: region.toLowerCase() } : {}) },
                });
                if (!active) return;
                if (response.error) throw new Error("voices request failed");
                const persona = new Map(styles.map((option) => [option.id, option]));
                // The speech-to-speech order, so both modes list voices alike.
                const rank = (name: string) => {
                    const index = styles.findIndex((option) => option.id === name);
                    return index === -1 ? styles.length : index;
                };
                setVoices(
                    (response.data?.voices ?? [])
                        .filter((voice) => voice.voice_id.startsWith(`${language}-`))
                        .sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
                        .map((voice) => ({
                            id: voice.voice_id,
                            label: voice.name,
                            gender: voice.gender,
                            description: persona.get(voice.name)?.description ?? null,
                            recommended: persona.get(voice.name)?.recommended ?? false,
                            preview_url: voice.preview_url,
                        })),
                );
            } catch (err) {
                if (!active) return;
                logger.error(`Failed to load voices: ${err}`);
                setError("Couldn't load the voices. Reload the page to try again.");
            }
        })();
        return () => {
            active = false;
        };
        // styles is catalog data and stable for the page.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [catalog, model, language]);

    if (error) return <p className="text-sm text-destructive">{error}</p>;
    if (voices === null) {
        return (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading voices
            </p>
        );
    }
    return (
        <VoiceCardPicker
            voices={voices}
            value={value}
            onChange={onChange}
            disabled={disabled}
            labelledBy={labelledBy}
            sampleNote="Each sample reads the same English sentence in that voice and accent."
        />
    );
}
