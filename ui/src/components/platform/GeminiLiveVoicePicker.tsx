"use client";

import type { PlatformCatalogOption } from "@/client/types.gen";
import { VoiceCardPicker } from "@/components/platform/VoiceCardPicker";

interface GeminiLiveVoicePickerProps {
    voices: PlatformCatalogOption[];
    value: string;
    onChange: (voice: string) => void;
    disabled?: boolean;
    labelledBy?: string;
}

/** The speech-to-speech voices, with a sample for each. */
export function GeminiLiveVoicePicker(props: GeminiLiveVoicePickerProps) {
    return (
        <VoiceCardPicker
            {...props}
            sampleNote="Samples are spoken in English. On calls the agent uses the same voice in the language chosen above."
        />
    );
}
