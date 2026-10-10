"use client";

import { AudioLines, Info, Lock, MessagesSquare, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
    OrganizationAiModelConfigurationV2,
    PlatformCatalogOption,
    PlatformModelCatalog,
    PlatformPipelineMode,
} from "@/client/types.gen";
import { GeminiLiveVoicePicker } from "@/components/platform/GeminiLiveVoicePicker";
import { PlatformTtsVoicePicker } from "@/components/platform/PlatformTtsVoicePicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
    buildPlatformConfiguration,
    languageLabel,
    type PlatformFormState,
    platformFormStateFromConfiguration,
    sttLanguagesFor,
    validatePlatformFormState,
    voiceInLanguage,
    voiceLocale,
} from "@/lib/platformModelConfig";
import { cn } from "@/lib/utils";

interface PlatformModelEditorProps {
    catalog: PlatformModelCatalog;
    // The stored configuration (any mode); non-platform ones start from defaults.
    configuration: unknown;
    onSave: (configuration: OrganizationAiModelConfigurationV2) => Promise<void>;
    submitLabel?: string;
    // Viewers without permission to change model settings.
    readOnly?: boolean;
}

const MODE_ICONS: Record<PlatformPipelineMode, typeof AudioLines> = {
    realtime: AudioLines,
    pipeline: MessagesSquare,
};

function sortedLanguages(codes: string[]): string[] {
    return [...codes].sort((a, b) => languageLabel(a).localeCompare(languageLabel(b)));
}

function OptionSelect({
    id,
    options,
    value,
    onChange,
    disabled,
}: {
    id: string;
    options: PlatformCatalogOption[];
    value: string;
    onChange: (value: string) => void;
    disabled: boolean;
}) {
    const selected = options.find((option) => option.id === value);
    return (
        <div className="space-y-1">
            <Select value={value} onValueChange={onChange} disabled={disabled}>
                <SelectTrigger id={id} className="w-full">
                    <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem key={option.id} value={option.id}>
                            {option.label}
                            {option.recommended ? " (recommended)" : ""}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            {selected?.description && <p className="text-xs text-muted-foreground">{selected.description}</p>}
        </div>
    );
}

function LanguageSelect({
    id,
    languages,
    value,
    onChange,
    disabled,
}: {
    id: string;
    languages: string[];
    value: string;
    onChange: (value: string) => void;
    disabled: boolean;
}) {
    const options = useMemo(() => sortedLanguages(languages), [languages]);
    return (
        <Select value={value} onValueChange={onChange} disabled={disabled}>
            <SelectTrigger id={id} className="w-full">
                <SelectValue placeholder="Select language" />
            </SelectTrigger>
            <SelectContent>
                {options.map((code) => (
                    <SelectItem key={code} value={code}>
                        {languageLabel(code)}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}

/**
 * The managed Models editor: how the agent talks, then the models, voice and
 * language for that path, all from the server's platform catalog. No keys,
 * providers or regions.
 */
export function PlatformModelEditor({
    catalog,
    configuration,
    onSave,
    submitLabel = "Save Configuration",
    readOnly = false,
}: PlatformModelEditorProps) {
    const initial = useMemo(
        () => platformFormStateFromConfiguration(configuration, catalog),
        [configuration, catalog],
    );
    const [state, setState] = useState<PlatformFormState>(initial.state);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [attempted, setAttempted] = useState(false);

    useEffect(() => {
        setState(initial.state);
        setAttempted(false);
        setError(null);
    }, [initial]);

    const locked = Boolean(catalog.locked);
    const disabled = locked || readOnly;
    const errors = validatePlatformFormState(state, catalog);
    const { realtime, pipeline } = catalog;

    const update = <K extends keyof PlatformFormState>(key: K, value: Partial<PlatformFormState[K]>) =>
        setState((current) => ({ ...current, [key]: { ...(current[key] as object), ...value } }));

    const changeTtsLanguage = (language: string) =>
        update("tts", {
            language,
            voice: voiceInLanguage(catalog, state.tts.model, state.tts.voice, language),
        });

    const changeTtsVoice = (voice: string) => {
        const locale = voiceLocale(voice);
        update("tts", {
            voice,
            ...(locale && pipeline.tts.languages.includes(locale) ? { language: locale } : {}),
        });
    };

    const save = async () => {
        setAttempted(true);
        setError(null);
        if (errors.length > 0) return;
        setSaving(true);
        try {
            await onSave(buildPlatformConfiguration(state));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save configuration");
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-6">
            {locked && (
                <div className="flex items-start gap-2 rounded-md border border-line bg-muted/40 px-4 py-3 text-sm">
                    <Lock className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>Model settings for this workspace are managed by Fallcha.ai support. Contact us to change them.</span>
                </div>
            )}
            {initial.migratedFrom && !disabled && (
                <div className="flex items-start gap-2 rounded-md border border-sky/40 bg-sky/10 px-4 py-3 text-sm">
                    <Info className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>Your agents use the default managed setup. Review and save to confirm your choice.</span>
                </div>
            )}
            {error && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                </div>
            )}

            <section className="space-y-3">
                <h2 className="text-lg font-semibold">How should your agent talk?</h2>
                <div role="radiogroup" aria-label="How should your agent talk?" className="grid gap-3 sm:grid-cols-2">
                    {catalog.modes.map((mode) => {
                        const Icon = MODE_ICONS[mode.id];
                        const selected = state.pipelineMode === mode.id;
                        return (
                            <button
                                key={mode.id}
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                disabled={disabled}
                                onClick={() => setState((current) => ({ ...current, pipelineMode: mode.id }))}
                                className={cn(
                                    "flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed",
                                    selected ? "border-primary ring-1 ring-primary" : "border-border hover:bg-accent",
                                )}
                            >
                                <span className="flex items-center gap-2 font-medium">
                                    <Icon className="h-4 w-4" />
                                    {mode.label}
                                    {mode.recommended && <Badge variant="secondary">Recommended</Badge>}
                                </span>
                                <span className="text-sm text-muted-foreground">{mode.description}</span>
                            </button>
                        );
                    })}
                </div>
            </section>

            {state.pipelineMode === "realtime" ? (
                <Card>
                    <CardContent className="grid gap-4 pt-6 sm:grid-cols-2">
                        <div className="space-y-2">
                            <Label htmlFor="platform-realtime-model">Model</Label>
                            <OptionSelect
                                id="platform-realtime-model"
                                options={realtime.models}
                                value={state.realtime.model}
                                onChange={(model) => update("realtime", { model })}
                                disabled={disabled}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="platform-realtime-language">Language</Label>
                            <LanguageSelect
                                id="platform-realtime-language"
                                languages={realtime.languages}
                                value={state.realtime.language}
                                onChange={(language) => update("realtime", { language })}
                                disabled={disabled}
                            />
                        </div>
                        <div className="space-y-2 sm:col-span-2">
                            <Label>Voice</Label>
                            <GeminiLiveVoicePicker
                                voices={realtime.voices}
                                value={state.realtime.voice}
                                onChange={(voice) => update("realtime", { voice })}
                                disabled={disabled}
                            />
                        </div>
                    </CardContent>
                </Card>
            ) : (
                <div className="space-y-4">
                    <Card>
                        <CardContent className="grid gap-4 pt-6 sm:grid-cols-2">
                            <h3 className="font-medium sm:col-span-2">Speech-to-text</h3>
                            <div className="space-y-2">
                                <Label htmlFor="platform-stt-model">Model</Label>
                                <OptionSelect
                                    id="platform-stt-model"
                                    options={pipeline.stt.models}
                                    value={state.stt.model}
                                    onChange={(model) => update("stt", { model })}
                                    disabled={disabled}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="platform-stt-language">Language</Label>
                                <LanguageSelect
                                    id="platform-stt-language"
                                    languages={sttLanguagesFor(catalog, state.stt.model)}
                                    value={state.stt.language}
                                    onChange={(language) => update("stt", { language })}
                                    disabled={disabled}
                                />
                            </div>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardContent className="grid gap-4 pt-6 sm:grid-cols-2">
                            <h3 className="font-medium sm:col-span-2">Language model</h3>
                            <div className="space-y-2">
                                <Label htmlFor="platform-llm-model">Model</Label>
                                <OptionSelect
                                    id="platform-llm-model"
                                    options={pipeline.llm.models}
                                    value={state.llm.model}
                                    onChange={(model) => update("llm", { model })}
                                    disabled={disabled}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="platform-llm-temperature">Temperature</Label>
                                <Input
                                    id="platform-llm-temperature"
                                    type="number"
                                    min={pipeline.llm.temperature_range.min}
                                    max={pipeline.llm.temperature_range.max}
                                    step={pipeline.llm.temperature_range.step}
                                    value={state.llm.temperature ?? ""}
                                    placeholder="Model default"
                                    disabled={disabled}
                                    onChange={(event) => {
                                        const value = event.currentTarget.valueAsNumber;
                                        update("llm", { temperature: Number.isFinite(value) ? value : null });
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">
                                    Lower values give more predictable replies. Leave blank for the model default.
                                </p>
                            </div>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardContent className="grid gap-4 pt-6 sm:grid-cols-2">
                            <h3 className="font-medium sm:col-span-2">Text-to-speech</h3>
                            {pipeline.tts.models.length > 1 && (
                                <div className="space-y-2 sm:col-span-2">
                                    <Label htmlFor="platform-tts-model">Model</Label>
                                    <OptionSelect
                                        id="platform-tts-model"
                                        options={pipeline.tts.models}
                                        value={state.tts.model}
                                        onChange={(model) => update("tts", { model })}
                                        disabled={disabled}
                                    />
                                </div>
                            )}
                            <div className="space-y-2">
                                <Label htmlFor="platform-tts-language">Voice language</Label>
                                <LanguageSelect
                                    id="platform-tts-language"
                                    languages={pipeline.tts.languages}
                                    value={state.tts.language}
                                    onChange={changeTtsLanguage}
                                    disabled={disabled}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="platform-tts-speed">Speed</Label>
                                <Input
                                    id="platform-tts-speed"
                                    type="number"
                                    min={pipeline.tts.speed_range.min}
                                    max={pipeline.tts.speed_range.max}
                                    step={pipeline.tts.speed_range.step}
                                    value={state.tts.speed}
                                    disabled={disabled}
                                    onChange={(event) => {
                                        const value = event.currentTarget.valueAsNumber;
                                        update("tts", { speed: Number.isFinite(value) ? value : pipeline.tts.defaults.speed });
                                    }}
                                />
                            </div>
                            <div className="space-y-2 sm:col-span-2">
                                <Label>Voice</Label>
                                {disabled ? (
                                    <p className="text-sm">{state.tts.voice}</p>
                                ) : (
                                    <PlatformTtsVoicePicker
                                        catalog={pipeline.tts.voice_catalog}
                                        model={state.tts.model}
                                        language={state.tts.language}
                                        value={state.tts.voice}
                                        onChange={changeTtsVoice}
                                    />
                                )}
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}

            {attempted && errors.length > 0 && (
                <ul className="space-y-1 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {errors.map((message) => (
                        <li key={message}>{message}</li>
                    ))}
                </ul>
            )}

            {!disabled && (
                <Button type="button" className="w-full" onClick={save} disabled={saving}>
                    <Save className="mr-2 h-4 w-4" />
                    {saving ? "Saving..." : submitLabel}
                </Button>
            )}
        </div>
    );
}
