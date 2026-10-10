"use client";

import { useAppConfig } from "@/context/AppConfigContext";

const HIGHLIGHTS = [
    "Done-for-you platform & configuration",
    "Speech-to-speech",
    "MCP-native",
];

/** Product highlights beside the auth form; the model claim follows the deployment. */
export function AuthHighlights() {
    const { config } = useAppConfig();
    const points = [
        ...HIGHLIGHTS,
        config?.platformModelsEnabled ? "Managed EU models, no API keys" : "BYOK - any model",
    ];
    return (
        <>
            {points.map((point) => (
                <li
                    key={point}
                    className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-medium text-zinc-300"
                >
                    {point}
                </li>
            ))}
        </>
    );
}
