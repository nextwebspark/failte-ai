"use client";

import { ALL_FILTER_VALUE, VoiceSelectorModal } from "@/components/VoiceSelectorModal";

interface PlatformTtsVoicePickerProps {
    // Provider id for the voice catalog endpoint (catalog `voice_catalog`).
    catalog: string;
    model: string;
    language: string;
    value: string;
    onChange: (voice: string) => void;
}

/**
 * Text-to-speech voice picker that opens on the selected voice language,
 * e.g. "en-GB" → English, British accent, any gender.
 */
export function PlatformTtsVoicePicker({ catalog, model, language, value, onChange }: PlatformTtsVoicePickerProps) {
    const [base, region] = language.split("-");
    return (
        <VoiceSelectorModal
            // Re-open on the new language after it changes.
            key={language}
            provider={catalog}
            model={model}
            value={value}
            onChange={onChange}
            defaultLanguage={base.toLowerCase()}
            defaultAccent={region ? region.toLowerCase() : ALL_FILTER_VALUE}
            defaultGender={ALL_FILTER_VALUE}
        />
    );
}
