"use client";

import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
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
    sttLanguageForModel,
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
    if (options.length === 1 && selected) {
        // Nothing to choose: show the model, not a one-item dropdown.
        return (
            <div className="space-y-1">
                <p id={id} className="text-sm font-medium">{selected.label}</p>
                {selected.description && <p className="text-xs text-muted-foreground">{selected.description}</p>}
            </div>
        );
    }
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
 * A number input that lets the field be emptied while typing; the value is
 * committed on blur (blank means *emptyValue*).
 */
function NumberField({
    id,
    value,
    emptyValue,
    range,
    placeholder,
    disabled,
    onChange,
}: {
    id: string;
    value: number | null;
    emptyValue: number | null;
    range: { min: number; max: number; step: number };
    placeholder?: string;
    disabled: boolean;
    onChange: (value: number | null) => void;
}) {
    const [text, setText] = useState(value === null ? "" : String(value));
    useEffect(() => setText(value === null ? "" : String(value)), [value]);
    const commit = (raw: string) => {
        const parsed = raw.trim() === "" ? emptyValue : Number(raw);
        onChange(parsed === null || Number.isFinite(parsed) ? parsed : emptyValue);
    };
    return (
        <Input
            id={id}
            type="number"
            min={range.min}
            max={range.max}
            step={range.step}
            value={text}
            placeholder={placeholder}
            disabled={disabled}
            onChange={(event) => {
                setText(event.currentTarget.value);
                // Keep the form value current for typed numbers; blanks wait for blur.
                if (event.currentTarget.value.trim() !== "") commit(event.currentTarget.value);
            }}
            onBlur={(event) => commit(event.currentTarget.value)}
        />
    );
}

function voiceName(voice: string): string {
    return voice.split("-").pop() || voice;
}

/**
 * The managed Models editor: how the agent talks, then the models, voice and
 * language for that path, all from the server's platform catalog. No keys,
 * providers or regions.
 *
 * The form resets when `configuration` or `catalog` change identity, so
 * callers pass values held in state, not literals rebuilt on each render.
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
    // The voice language follows the transcription language until the
    // customer picks a voice language or voice themselves.
    const [ttsTouched, setTtsTouched] = useState(false);

    useEffect(() => {
        setState(initial.state);
        setAttempted(false);
        setError(null);
        setTtsTouched(false);
    }, [initial]);

    const locked = Boolean(catalog.locked);
    const disabled = locked || readOnly;
    const errors = validatePlatformFormState(state, catalog);
    const { realtime, pipeline } = catalog;

    const update = <K extends keyof PlatformFormState>(key: K, value: Partial<PlatformFormState[K]>) =>
        setState((current) => ({ ...current, [key]: { ...(current[key] as object), ...value } }));

    const ttsLanguageUpdate = (language: string) => ({
        language,
        voice: voiceInLanguage(catalog, state.tts.model, state.tts.voice, language),
    });

    const changeTtsLanguage = (language: string) => {
        setTtsTouched(true);
        update("tts", ttsLanguageUpdate(language));
    };

    const changeTtsVoice = (voice: string) => {
        setTtsTouched(true);
        const locale = voiceLocale(voice);
        update("tts", {
            voice,
            ...(locale && pipeline.tts.languages.includes(locale) ? { language: locale } : {}),
        });
    };

    const changeSttModel = (model: string) =>
        update("stt", { model, language: sttLanguageForModel(catalog, model, state.stt.language) });

    const changeSttLanguage = (language: string) => {
        update("stt", { language });
        if (!ttsTouched && pipeline.tts.languages.includes(language) && language !== state.tts.language) {
            update("tts", ttsLanguageUpdate(language));
        }
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
                <RadioGroupPrimitive.Root
                    value={state.pipelineMode}
                    onValueChange={(mode) =>
                        setState((current) => ({ ...current, pipelineMode: mode as PlatformPipelineMode }))
                    }
                    disabled={disabled}
                    aria-label="How should your agent talk?"
                    className="grid gap-3 sm:grid-cols-2"
                >
                    {catalog.modes.map((mode) => {
                        const Icon = MODE_ICONS[mode.id];
                        const selected = state.pipelineMode === mode.id;
                        return (
                            <RadioGroupPrimitive.Item
                                key={mode.id}
                                value={mode.id}
                                className={cn(
                                    "flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed",
                                    selected ? "border-primary ring-1 ring-primary" : "border-border hover:bg-accent",
                                )}
                            >
                                <span className="flex items-center gap-2 font-medium">
                                    <Icon className="h-4 w-4" />
                                    {mode.label}
                                    {mode.recommended && <Badge variant="secondary">Recommended</Badge>}
                                </span>
                                <span className="text-sm text-muted-foreground">{mode.description}</span>
                            </RadioGroupPrimitive.Item>
                        );
                    })}
                </RadioGroupPrimitive.Root>
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
                            <Label id="platform-realtime-voice-label">Voice</Label>
                            <GeminiLiveVoicePicker
                                labelledBy="platform-realtime-voice-label"
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
                                    onChange={changeSttModel}
                                    disabled={disabled}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="platform-stt-language">Language</Label>
                                <LanguageSelect
                                    id="platform-stt-language"
                                    languages={sttLanguagesFor(catalog, state.stt.model)}
                                    value={state.stt.language}
                                    onChange={changeSttLanguage}
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
                                <NumberField
                                    id="platform-llm-temperature"
                                    value={state.llm.temperature}
                                    emptyValue={null}
                                    range={pipeline.llm.temperature_range}
                                    placeholder="Model default"
                                    disabled={disabled}
                                    onChange={(temperature) => update("llm", { temperature })}
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
                                <NumberField
                                    id="platform-tts-speed"
                                    value={state.tts.speed}
                                    emptyValue={pipeline.tts.defaults.speed}
                                    range={pipeline.tts.speed_range}
                                    disabled={disabled}
                                    onChange={(speed) => update("tts", { speed: speed ?? pipeline.tts.defaults.speed })}
                                />
                            </div>
                            <div className="space-y-2 sm:col-span-2">
                                <Label id="platform-tts-voice-label">Voice</Label>
                                {disabled ? (
                                    <p className="text-sm" aria-labelledby="platform-tts-voice-label">
                                        {state.tts.voice
                                            ? `${voiceName(state.tts.voice)} · ${languageLabel(state.tts.language)}`
                                            : "No voice selected"}
                                    </p>
                                ) : (
                                    <PlatformTtsVoicePicker
                                        catalog={pipeline.tts.voice_catalog}
                                        model={state.tts.model}
                                        language={state.tts.language}
                                        value={state.tts.voice}
                                        onChange={changeTtsVoice}
                                    />
                                )}
                                {!state.tts.voice && !disabled && (
                                    <p className="text-xs text-muted-foreground">
                                        Pick a voice for {languageLabel(state.tts.language)}.
                                    </p>
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
