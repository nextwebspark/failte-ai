"use client";

import { format } from "date-fns";
import { BookA, CalendarIcon, Clipboard, Download, ExternalLink, FileDown, Fingerprint, Loader2, Mic, Pause, PhoneCall, PhoneOff, Play, Plus, Settings, Trash2Icon, Upload, Variable, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    downloadWorkflowReportApiV1WorkflowWorkflowIdReportGet,
    getAmbientNoiseUploadUrlApiV1WorkflowAmbientNoiseUploadUrlPost,
} from "@/client/sdk.gen";
import { LLMConfigSelector } from "@/components/LLMConfigSelector";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAppConfig } from "@/context/AppConfigContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useUnsavedChanges, useUnsavedChangesContext } from "@/context/UnsavedChangesContext";
import { useAudioPlayback } from "@/hooks/useAudioPlayback";
import { copyTextToClipboard } from "@/lib/clipboard";
import logger from "@/lib/logger";
import { cn } from "@/lib/utils";
import {
    type AmbientNoiseConfiguration,
    type CallDispositionOption,
    DEFAULT_TURN_START_MIN_WORDS,
    DEFAULT_VOICEMAIL_DETECTION_CONFIGURATION,
    type ExternalPBXFieldMapping,
    TURN_START_STRATEGY_OPTIONS,
    type TurnStartStrategy,
    type TurnStopStrategy,
    type VoicemailDetectionConfiguration,
    type WorkflowConfigurations,
} from "@/types/workflow-configurations";

import { type AgentSectionContext, AgentSectionShell } from "../components/AgentSectionShell";
import { AnswerSupervisorFields, isVoicemailMessageMissing, readAnswerSupervisorSettings } from "../components/AnswerSupervisorFields";
import {
    CallDispositionEditor,
    type CallDispositionRow,
    createCallDispositionRows,
    normalizeCallDispositions,
    validateCallDispositionRows,
} from "./components/CallDispositionEditor";
import { SettingBlock, SettingRow, SettingsSection } from "./SettingsLayout";
import { SettingsSaveProvider, useSettingsSection } from "./SettingsSaveBar";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PUBLISH_WORKFLOW_REMINDER = "Publish the agent to apply the changes.";

// The section index. Model overrides ("Model and voice") and the website
// widget ("Deployment") are agent nav rows of their own, so they are not here.
const NAV_ITEMS = [
    { id: "general", label: "General" },
    { id: "call", label: "Call behaviour" },
    { id: "variables", label: "Variables" },
    { id: "dictionary", label: "Dictionary" },
    { id: "voicemail", label: "Voicemail and screening" },
    { id: "identity", label: "Identity" },
    { id: "recordings", label: "Recordings" },
    { id: "report", label: "Reporting" },
];

// ---------------------------------------------------------------------------
// Section: Report
// ---------------------------------------------------------------------------

function ReportSection({ workflowId }: { workflowId: number }) {
    const [startDate, setStartDate] = useState<Date | undefined>(undefined);
    const [startTime, setStartTime] = useState("00:00");
    const [endDate, setEndDate] = useState<Date | undefined>(undefined);
    const [endTime, setEndTime] = useState("23:59");
    const [isPopoverOpen, setIsPopoverOpen] = useState(false);
    const [isDownloading, setIsDownloading] = useState(false);

    const buildDateTime = (date: Date | undefined, time: string): string | undefined => {
        if (!date) return undefined;
        const [hours, minutes] = time.split(":").map(Number);
        const combined = new Date(date);
        combined.setHours(hours, minutes, 0, 0);
        return combined.toISOString();
    };

    const handleDownload = async () => {
        setIsDownloading(true);
        setIsPopoverOpen(false);
        try {
            const response = await downloadWorkflowReportApiV1WorkflowWorkflowIdReportGet({
                path: { workflow_id: workflowId },
                query: {
                    start_date: buildDateTime(startDate, startTime),
                    end_date: buildDateTime(endDate, endTime),
                },
                parseAs: "blob",
            });

            if (response.data) {
                const blob = response.data as Blob;
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `workflow_${workflowId}_report.csv`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            } else {
                toast.error("Failed to download report");
            }
        } catch (err) {
            logger.error(`Failed to download workflow report: ${err}`);
            toast.error("Failed to download report");
        } finally {
            setIsDownloading(false);
        }
    };

    const handleClear = () => {
        setStartDate(undefined);
        setStartTime("00:00");
        setEndDate(undefined);
        setEndTime("23:59");
    };

    return (
        <SettingsSection id="report" icon={FileDown} title="Reporting" description="Completed calls for this agent as a CSV file.">
            <SettingRow compact label="Download report" hint="All calls, or only those in a date range.">
            <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
                <PopoverTrigger asChild>
                    <Button variant="outline" size="sm" disabled={isDownloading}>
                        <Download className="h-4 w-4 mr-2" />
                        Download report
                    </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-4" align="start">
                    <div className="space-y-4">
                        <div className="text-sm font-medium">Filter by date range</div>
                        <div className="grid gap-3">
                        <div className="space-y-1.5">
                            <Label className="text-xs">From</Label>
                            <div className="flex gap-2">
                                <Popover>
                                    <PopoverTrigger asChild>
                                    <Button variant="outline" size="sm" className="w-[140px] justify-start text-left font-normal">
                                        <CalendarIcon className="mr-2 h-3.5 w-3.5" />
                                        {startDate ? format(startDate, "MMM dd, yyyy") : "Start date"}
                                    </Button>
                                    </PopoverTrigger>
                                    <PopoverContent className="w-auto p-0" align="start">
                                    <Calendar
                                        mode="single"
                                        selected={startDate}
                                        onSelect={setStartDate}
                                        disabled={(date) => (endDate ? date > endDate : false)}
                                    />
                                    </PopoverContent>
                                </Popover>
                                <Input
                                    type="time"
                                    value={startTime}
                                    onChange={(e) => setStartTime(e.target.value)}
                                    className="w-[100px] h-8 text-xs"
                                />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-xs">To</Label>
                            <div className="flex gap-2">
                                <Popover>
                                    <PopoverTrigger asChild>
                                    <Button variant="outline" size="sm" className="w-[140px] justify-start text-left font-normal">
                                        <CalendarIcon className="mr-2 h-3.5 w-3.5" />
                                        {endDate ? format(endDate, "MMM dd, yyyy") : "End date"}
                                    </Button>
                                    </PopoverTrigger>
                                    <PopoverContent className="w-auto p-0" align="start">
                                    <Calendar
                                        mode="single"
                                        selected={endDate}
                                        onSelect={setEndDate}
                                        disabled={(date) => (startDate ? date < startDate : false)}
                                    />
                                    </PopoverContent>
                                </Popover>
                                <Input
                                    type="time"
                                    value={endTime}
                                    onChange={(e) => setEndTime(e.target.value)}
                                    className="w-[100px] h-8 text-xs"
                                />
                            </div>
                        </div>
                        </div>
                        <Separator />
                        <div className="flex justify-between">
                        <Button variant="ghost" size="sm" onClick={handleClear}>
                            Clear
                        </Button>
                        <Button size="sm" onClick={handleDownload} disabled={isDownloading}>
                            <Download className="h-3.5 w-3.5 mr-1.5" />
                            {startDate || endDate ? "Download Filtered" : "Download All"}
                        </Button>
                        </div>
                    </div>
                </PopoverContent>
            </Popover>
            </SettingRow>
        </SettingsSection>
    );
}

// ---------------------------------------------------------------------------
// Section: General
// ---------------------------------------------------------------------------

const MAX_AMBIENT_NOISE_FILE_SIZE = 10 * 1024 * 1024; // 10MB

function GeneralSection({
    workflowConfigurations,
    defaultCallDispositions,
    workflowName,
    workflowId,
}: {
    workflowConfigurations: WorkflowConfigurations;
    defaultCallDispositions: CallDispositionOption[];
    workflowName: string;
    workflowId: number;
}) {
    const { externalPbxIntegrationsEnabled } = useOrgConfig();
    const [name, setName] = useState(workflowName);
    const [ambientNoiseConfig, setAmbientNoiseConfig] = useState<AmbientNoiseConfiguration>(
        workflowConfigurations.ambient_noise_configuration,
    );
    const [maxCallDuration, setMaxCallDuration] = useState(workflowConfigurations.max_call_duration);
    const [maxUserIdleTimeout, setMaxUserIdleTimeout] = useState(workflowConfigurations.max_user_idle_timeout);
    const [smartTurnStopSecs, setSmartTurnStopSecs] = useState(workflowConfigurations.smart_turn_stop_secs);
    const [turnStartStrategy, setTurnStartStrategy] = useState<TurnStartStrategy>(
        workflowConfigurations.turn_start_strategy,
    );
    const [turnStartMinWords, setTurnStartMinWords] = useState(
        workflowConfigurations.turn_start_min_words,
    );
    const [turnStopStrategy, setTurnStopStrategy] = useState<TurnStopStrategy>(
        workflowConfigurations.turn_stop_strategy,
    );
    const [contextCompactionEnabled, setContextCompactionEnabled] = useState(
        workflowConfigurations.context_compaction_enabled,
    );
    const [ttsCacheEnabled, setTtsCacheEnabled] = useState(
        workflowConfigurations.tts_cache_enabled,
    );
    const [skillsEnabled, setSkillsEnabled] = useState(
        workflowConfigurations.skills_enabled,
    );
    const [callDispositionRows, setCallDispositionRows] = useState<CallDispositionRow[]>(
        () => createCallDispositionRows(workflowConfigurations.call_dispositions),
    );
    const [includeTranscriptEndTimestamps, setIncludeTranscriptEndTimestamps] = useState(
        workflowConfigurations.transcript_configuration?.include_end_timestamps ?? false,
    );
    const [externalPbxFieldMappings, setExternalPbxFieldMappings] = useState<ExternalPBXFieldMapping[]>(
        workflowConfigurations.external_pbx_field_mappings,
    );
    const [externalPbxLeadHeaders, setExternalPbxLeadHeaders] = useState<string[]>(
        workflowConfigurations.external_pbx_lead_headers,
    );
    const [isUploadingAudio, setIsUploadingAudio] = useState(false);
    const [audioUploadError, setAudioUploadError] = useState<string | null>(null);
    const ambientFileInputRef = useRef<HTMLInputElement>(null);
    const { playingId, toggle: togglePlayback } = useAudioPlayback();
    const selectedTurnStartStrategy = TURN_START_STRATEGY_OPTIONS.find(
        (option) => option.value === turnStartStrategy,
    );
    const externalPbxFieldMappingsValid = externalPbxFieldMappings.every(
        (mapping) =>
            Boolean(mapping.context_path.trim()) &&
            /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(mapping.destination_field.trim()),
    );
    const externalPbxLeadHeadersValid = externalPbxLeadHeaders.every((field) =>
        /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(field.trim()),
    );
    const externalPbxSettingsValid =
        externalPbxFieldMappingsValid && externalPbxLeadHeadersValid;
    const normalizedCallDispositions = useMemo(
        () => normalizeCallDispositions(callDispositionRows),
        [callDispositionRows],
    );
    const callDispositionsValid = useMemo(
        () => validateCallDispositionRows(callDispositionRows).isValid,
        [callDispositionRows],
    );

    // The form spans two cards; each gets its own unsaved dot in the index.
    // The name is saved trimmed, so compare it trimmed (or a trailing space
    // would leave the section dirty after every save).
    const identityDirty =
        name.trim() !== workflowName.trim() ||
        JSON.stringify(ambientNoiseConfig) !== JSON.stringify(workflowConfigurations.ambient_noise_configuration) ||
        maxCallDuration !== workflowConfigurations.max_call_duration ||
        maxUserIdleTimeout !== workflowConfigurations.max_user_idle_timeout;
    const behaviourDirty =
        smartTurnStopSecs !== workflowConfigurations.smart_turn_stop_secs ||
        turnStartStrategy !== workflowConfigurations.turn_start_strategy ||
        turnStartMinWords !== workflowConfigurations.turn_start_min_words ||
        turnStopStrategy !== workflowConfigurations.turn_stop_strategy ||
        contextCompactionEnabled !== workflowConfigurations.context_compaction_enabled ||
        ttsCacheEnabled !== workflowConfigurations.tts_cache_enabled ||
        skillsEnabled !== workflowConfigurations.skills_enabled ||
        JSON.stringify(normalizedCallDispositions) !== JSON.stringify(workflowConfigurations.call_dispositions) ||
        includeTranscriptEndTimestamps !==
            (workflowConfigurations.transcript_configuration?.include_end_timestamps ?? false) ||
        JSON.stringify(externalPbxFieldMappings) !== JSON.stringify(workflowConfigurations.external_pbx_field_mappings) ||
        JSON.stringify(externalPbxLeadHeaders) !== JSON.stringify(workflowConfigurations.external_pbx_lead_headers);
    const isDirty = identityDirty || behaviourDirty;
    useUnsavedChanges("general", identityDirty);
    useUnsavedChanges("call", behaviourDirty);

    const blocker = !name.trim()
        ? "Add an agent name"
        : isUploadingAudio
            ? "Wait for the audio upload to finish"
            : !callDispositionsValid
                ? "Fix the call outcomes"
                : externalPbxIntegrationsEnabled && !externalPbxSettingsValid
                    ? "Fix the PBX fields"
                    : null;

    // The rows the last save sent, so a save doesn't rewrite rows edited meanwhile.
    const savedDispositionRows = useRef<CallDispositionRow[] | null>(null);

    useSettingsSection("general", {
        label: [identityDirty && "General", behaviourDirty && "Call behaviour"].filter(Boolean).join(", ") || "General",
        dirty: isDirty,
        blocker,
        patch: () => {
            savedDispositionRows.current = callDispositionRows;
            return {
                workflowName: name.trim(),
                configurations: {
                    ambient_noise_configuration: ambientNoiseConfig,
                    max_call_duration: maxCallDuration,
                    max_user_idle_timeout: maxUserIdleTimeout,
                    smart_turn_stop_secs: smartTurnStopSecs,
                    turn_start_strategy: turnStartStrategy,
                    turn_start_min_words: turnStartMinWords,
                    turn_stop_strategy: turnStopStrategy,
                    context_compaction_enabled: contextCompactionEnabled,
                    tts_cache_enabled: ttsCacheEnabled,
                    skills_enabled: skillsEnabled,
                    call_dispositions: normalizedCallDispositions,
                    transcript_configuration: {
                        ...(workflowConfigurations.transcript_configuration ?? {}),
                        include_end_timestamps: includeTranscriptEndTimestamps,
                    },
                    external_pbx_field_mappings: externalPbxFieldMappings,
                    external_pbx_lead_headers: externalPbxLeadHeaders.map((field) => field.trim()),
                },
            };
        },
        // Show the dispositions the way they were saved (trimmed, normalised),
        // unless they were edited while the save was in flight.
        afterSave: () =>
            setCallDispositionRows((current) => {
                if (current !== savedDispositionRows.current) return current;
                const normalized = normalizeCallDispositions(current);
                return current.map((row, index) => ({ ...row, ...normalized[index] }));
            }),
    });

    const handleAmbientFileUpload = async (file: File) => {
        if (file.size > MAX_AMBIENT_NOISE_FILE_SIZE) {
            setAudioUploadError(`File too large (${(file.size / (1024 * 1024)).toFixed(1)}MB). Maximum is 10MB.`);
            return;
        }

        setIsUploadingAudio(true);
        setAudioUploadError(null);

        try {
            // 1. Get presigned upload URL
            const res = await getAmbientNoiseUploadUrlApiV1WorkflowAmbientNoiseUploadUrlPost({
                body: {
                    workflow_id: Number(workflowId),
                    filename: file.name,
                    mime_type: file.type || "audio/wav",
                    file_size: file.size,
                },
            });

            if (res.error || !res.data?.upload_url) {
                throw new Error("Failed to get upload URL");
            }

            const data = res.data;

            // 2. Upload file to storage
            const uploadRes = await fetch(data.upload_url, {
                method: "PUT",
                body: file,
                headers: { "Content-Type": file.type || "audio/wav" },
            });
            if (!uploadRes.ok) {
                throw new Error("File upload failed");
            }

            // 3. Update config with storage reference
            setAmbientNoiseConfig((prev) => ({
                ...prev,
                storage_key: data.storage_key,
                storage_backend: data.storage_backend,
                original_filename: file.name,
            }));
        } catch (err) {
            setAudioUploadError(err instanceof Error ? err.message : "Upload failed");
        } finally {
            setIsUploadingAudio(false);
            if (ambientFileInputRef.current) ambientFileInputRef.current.value = "";
        }
    };

    const handleRemoveCustomAudio = () => {
        setAmbientNoiseConfig((prev) => ({
            enabled: prev.enabled,
            volume: prev.volume,
        }));
    };

    return (
        <>
            <SettingsSection id="general" icon={Settings} tone="brand" title="General" description="Name, background sound and call limits.">
                <SettingRow label="Agent name" htmlFor="workflow_name" hint="Shown in lists, reports and the test panel.">
                    <Input
                        id="workflow_name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Untitled agent"
                        className="w-full"
                    />
                </SettingRow>
                <SettingRow
                    compact
                    label="Ambient noise"
                    htmlFor="ambient-noise-enabled"
                    hint="Plays quietly under the agent's voice so silence doesn't sound like a dropped line."
                >
                    <Switch
                        id="ambient-noise-enabled"
                        checked={ambientNoiseConfig.enabled}
                        onCheckedChange={(checked) =>
                            setAmbientNoiseConfig((prev) => ({ ...prev, enabled: checked }))
                        }
                    />
                </SettingRow>
                {ambientNoiseConfig.enabled && (
                    <SettingBlock>
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <Label htmlFor="ambient-volume" className="text-xs">Volume</Label>
                                <Input
                                    id="ambient-volume"
                                    type="number"
                                    step="0.1"
                                    min="0"
                                    max="1"
                                    value={ambientNoiseConfig.volume}
                                    onChange={(e) => {
                                        const value = parseFloat(e.target.value);
                                        if (!isNaN(value)) setAmbientNoiseConfig((prev) => ({ ...prev, volume: value }));
                                    }}
                                />
                            </div>

                            {/* Custom audio file */}
                            <div className="space-y-2">
                                <Label className="text-xs">Custom audio file</Label>
                                <p className="text-xs text-muted-foreground">
                                    Upload your own audio file or use the default office ambience.
                                </p>

                                {ambientNoiseConfig.storage_key ? (
                                    <div className="flex items-center gap-2 rounded-md border p-2 bg-muted/10">
                                        <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono truncate flex-1">
                                            {ambientNoiseConfig.original_filename || "Custom audio"}
                                        </code>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="ghost"
                                            className="h-6 w-6 p-0 shrink-0"
                                            onClick={async () => {
                                                try {
                                                    await togglePlayback(
                                                        "ambient-noise",
                                                        ambientNoiseConfig.storage_key!,
                                                        ambientNoiseConfig.storage_backend,
                                                    );
                                                } catch {
                                                    setAudioUploadError("Failed to play audio");
                                                }
                                            }}
                                        >
                                            {playingId === "ambient-noise" ? (
                                                <Pause className="w-3.5 h-3.5" />
                                            ) : (
                                                <Play className="w-3.5 h-3.5" />
                                            )}
                                        </Button>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="ghost"
                                            className="h-6 w-6 p-0 shrink-0"
                                            onClick={handleRemoveCustomAudio}
                                        >
                                            <X className="w-3.5 h-3.5" />
                                        </Button>
                                    </div>
                                ) : (
                                    <div>
                                        <input
                                            ref={ambientFileInputRef}
                                            type="file"
                                            accept="audio/*"
                                            onChange={(e) => {
                                                const file = e.target.files?.[0];
                                                if (file) handleAmbientFileUpload(file);
                                            }}
                                            className="hidden"
                                        />
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            className="text-sm font-normal"
                                            onClick={() => ambientFileInputRef.current?.click()}
                                            disabled={isUploadingAudio}
                                        >
                                            {isUploadingAudio ? (
                                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                            ) : (
                                                <Upload className="w-4 h-4 mr-2" />
                                            )}
                                            {isUploadingAudio ? "Uploading..." : "Upload audio file (max 10MB)"}
                                        </Button>
                                    </div>
                                )}

                                {audioUploadError && (
                                    <p className="text-xs text-destructive">{audioUploadError}</p>
                                )}

                                {!ambientNoiseConfig.storage_key && (
                                    <p className="text-xs text-muted-foreground italic">
                                        Using default office ambience
                                    </p>
                                )}
                            </div>
                        </div>
                    </SettingBlock>
                )}
                <SettingRow compact label="Maximum call length" htmlFor="max_call_duration" hint="In seconds. The agent wraps up when it is reached. Default 600 (10 minutes).">
                    <Input
                        id="max_call_duration"
                        type="number"
                        min="1"
                        value={maxCallDuration}
                        onChange={(e) => {
                            const value = parseInt(e.target.value);
                            if (!isNaN(value) && value > 0) setMaxCallDuration(value);
                        }}
                        className="w-[110px] text-right font-mono"
                    />
                </SettingRow>
                <SettingRow compact label="Caller idle timeout" htmlFor="max_user_idle_timeout" hint="In seconds of silence from the caller before the agent checks in. Default 10.">
                    <Input
                        id="max_user_idle_timeout"
                        type="number"
                        min="1"
                        value={maxUserIdleTimeout}
                        onChange={(e) => {
                            const value = parseInt(e.target.value);
                            if (!isNaN(value) && value > 0) setMaxUserIdleTimeout(value);
                        }}
                        className="w-[110px] text-right font-mono"
                    />
                </SettingRow>
            </SettingsSection>

            <SettingsSection id="call" icon={PhoneCall} tone="sky" title="Call behaviour" description="How the agent listens, when it can be interrupted, and what it records.">
                <SettingRow
                    label="Turn detection"
                    htmlFor="turn_stop_strategy"
                    hint={turnStopStrategy === "transcription"
                        ? "Best for short answers. Ends the caller's turn when the transcription looks complete."
                        : "Best for longer answers with pauses. A model detects the end of the caller's turn."}
                >
                    <Select
                        value={turnStopStrategy}
                        onValueChange={(value: TurnStopStrategy) => setTurnStopStrategy(value)}
                    >
                        <SelectTrigger id="turn_stop_strategy" className="w-full">
                            <SelectValue placeholder="Select strategy" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="transcription">Transcription-based</SelectItem>
                            <SelectItem value="turn_analyzer">Smart turn analyzer</SelectItem>
                        </SelectContent>
                    </Select>
                </SettingRow>
                {turnStopStrategy === "turn_analyzer" && (
                    <SettingRow
                        compact
                        label="Incomplete turn timeout"
                        htmlFor="smart_turn_stop_secs"
                        hint="Seconds of silence before an unfinished turn ends. Default 2."
                    >
                        <Input
                            id="smart_turn_stop_secs"
                            type="number"
                            step="0.5"
                            min="0.5"
                            max="10"
                            value={smartTurnStopSecs}
                            onChange={(e) => {
                                const value = parseFloat(e.target.value);
                                if (!isNaN(value) && value >= 0.5) setSmartTurnStopSecs(value);
                            }}
                            className="w-[110px] text-right font-mono"
                        />
                    </SettingRow>
                )}
                <SettingRow label="Interruptions" htmlFor="turn_start_strategy" hint={selectedTurnStartStrategy?.description}>
                    <Select
                        value={turnStartStrategy}
                        onValueChange={(value: TurnStartStrategy) => setTurnStartStrategy(value)}
                    >
                        <SelectTrigger id="turn_start_strategy" className="w-full">
                            <SelectValue placeholder="Select strategy" />
                        </SelectTrigger>
                        <SelectContent>
                            {TURN_START_STRATEGY_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </SettingRow>
                {turnStartStrategy === "min_words" && (
                    <SettingRow
                        compact
                        label="Words before an interruption"
                        htmlFor="turn_start_min_words"
                        hint={`Transcribed words the caller must say to interrupt. Default ${DEFAULT_TURN_START_MIN_WORDS}.`}
                    >
                        <Input
                            id="turn_start_min_words"
                            type="number"
                            step="1"
                            min="1"
                            max="10"
                            value={turnStartMinWords}
                            onChange={(e) => {
                                const value = parseInt(e.target.value);
                                if (!isNaN(value) && value >= 1) setTurnStartMinWords(value);
                            }}
                            className="w-[110px] text-right font-mono"
                        />
                    </SettingRow>
                )}
                <SettingRow
                    compact
                    label="Timestamped transcript"
                    htmlFor="transcript-end-timestamps-enabled"
                    hint="Adds start and end times for each line of the uploaded transcript."
                >
                    <Switch
                        id="transcript-end-timestamps-enabled"
                        checked={includeTranscriptEndTimestamps}
                        onCheckedChange={setIncludeTranscriptEndTimestamps}
                    />
                </SettingRow>
                {includeTranscriptEndTimestamps && (
                    <SettingBlock>
                        <pre className="whitespace-pre-wrap rounded-md border border-line bg-panel-2 p-3 text-xs leading-relaxed text-ink-3">
                            {`[2026-07-06T10:00:00.000Z -> 2026-07-06T10:00:04.800Z] assistant: Can you confirm your date of birth?
[2026-07-06T10:00:06.200Z -> 2026-07-06T10:00:08.700Z] user: January fifth, nineteen ninety.`}
                        </pre>
                    </SettingBlock>
                )}
                <SettingRow
                    compact
                    label="Context compaction"
                    htmlFor="context-compaction-enabled"
                    hint="Summarises the conversation when moving between steps. Ignored in speech-to-speech (Realtime) mode."
                >
                    <Switch
                        id="context-compaction-enabled"
                        checked={contextCompactionEnabled}
                        onCheckedChange={setContextCompactionEnabled}
                    />
                </SettingRow>
                <SettingRow
                    compact
                    label="Skills"
                    htmlFor="skills-enabled"
                    hint="Adds a short skills list and two tools to each step. Turn off for latency-critical agents."
                >
                    <Switch id="skills-enabled" checked={skillsEnabled} onCheckedChange={setSkillsEnabled} />
                </SettingRow>
                <SettingRow
                    compact
                    label="Speech caching"
                    htmlFor="tts-cache-enabled"
                    hint="Reuses audio for repeated phrases for 24 hours, to answer faster and cost less. MiniMax voices only."
                >
                    <Switch id="tts-cache-enabled" checked={ttsCacheEnabled} onCheckedChange={setTtsCacheEnabled} />
                </SettingRow>
                <SettingBlock>
                    <CallDispositionEditor
                        rows={callDispositionRows}
                        onChange={setCallDispositionRows}
                        defaultDispositions={defaultCallDispositions}
                    />
                </SettingBlock>
                {externalPbxIntegrationsEnabled && (
                    <SettingBlock>
                        {/* External PBX field updates */}
                        <div className="space-y-4">
                            <div>
                                <h3 className="text-sm font-medium">External PBX field updates</h3>
                                <p className="text-xs text-muted-foreground mt-0.5">
                                    Optionally copy final gathered-context values into provider-native fields before transfer or hangup.
                                </p>
                            </div>
                            <div className="flex items-center justify-between">
                                <Label className="text-sm">Field mappings</Label>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setExternalPbxFieldMappings((current) => [
                                        ...current,
                                        { context_path: "", destination_field: "" },
                                    ])}
                                >
                                    <Plus className="mr-1 h-4 w-4" /> Add mapping
                                </Button>
                            </div>
                            <div className="space-y-2">
                                {externalPbxFieldMappings.map((mapping, index) => (
                                    <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                                        <Input
                                            aria-label={`Gathered context field ${index + 1}`}
                                            value={mapping.context_path}
                                            onChange={(event) => setExternalPbxFieldMappings((current) =>
                                                current.map((item, itemIndex) =>
                                                    itemIndex === index
                                                        ? { ...item, context_path: event.target.value }
                                                        : item,
                                                )
                                            )}
                                            placeholder="qualified"
                                        />
                                        <Input
                                            aria-label={`External PBX destination field ${index + 1}`}
                                            value={mapping.destination_field}
                                            onChange={(event) => setExternalPbxFieldMappings((current) =>
                                                current.map((item, itemIndex) =>
                                                    itemIndex === index
                                                        ? { ...item, destination_field: event.target.value }
                                                        : item,
                                                )
                                            )}
                                            placeholder="address3"
                                        />
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon"
                                            aria-label={`Remove external PBX field mapping ${index + 1}`}
                                            onClick={() => setExternalPbxFieldMappings((current) =>
                                                current.filter((_, itemIndex) => itemIndex !== index)
                                            )}
                                        >
                                            <Trash2Icon className="h-4 w-4" />
                                        </Button>
                                    </div>
                                ))}
                                {externalPbxFieldMappings.length === 0 && (
                                    <p className="text-xs text-muted-foreground">
                                        No external fields will be updated. Context names may be direct extracted-variable names or paths such as extracted_variables.qualified.
                                    </p>
                                )}
                                {!externalPbxFieldMappingsValid && (
                                    <p className="text-xs text-destructive">
                                        Each mapping needs a context field and a destination field containing only letters, numbers, and underscores.
                                    </p>
                                )}
                            </div>

                            <div className="space-y-4 border-t pt-4">
                                <div>
                                    <h3 className="text-sm font-medium">Lead fields to capture</h3>
                                    <p className="text-xs text-muted-foreground mt-0.5">
                                        Extra lead fields to read from the inbound call, named without the header prefix
                                        (<code>first_name</code> reads <code>X-VICIDIAL-first_name</code>). Captured values are
                                        addressable in prompts as <code>{"{{initial_context.external_pbx_call.lead.<field>}}"}</code>.
                                        Each field adds one request during call setup, so list only what the agent uses.
                                    </p>
                                </div>
                                <div className="flex items-center justify-between">
                                    <Label className="text-sm">Lead fields</Label>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setExternalPbxLeadHeaders((current) => [...current, ""])}
                                    >
                                        <Plus className="mr-1 h-4 w-4" /> Add field
                                    </Button>
                                </div>
                                <div className="space-y-2">
                                    {externalPbxLeadHeaders.map((field, index) => (
                                        <div key={index} className="grid grid-cols-[1fr_auto] gap-2">
                                            <Input
                                                aria-label={`External PBX lead field ${index + 1}`}
                                                value={field}
                                                onChange={(event) => setExternalPbxLeadHeaders((current) =>
                                                    current.map((item, itemIndex) =>
                                                        itemIndex === index ? event.target.value : item,
                                                    )
                                                )}
                                                placeholder="first_name"
                                            />
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="icon"
                                                aria-label={`Remove external PBX lead field ${index + 1}`}
                                                onClick={() => setExternalPbxLeadHeaders((current) =>
                                                    current.filter((_, itemIndex) => itemIndex !== index)
                                                )}
                                            >
                                                <Trash2Icon className="h-4 w-4" />
                                            </Button>
                                        </div>
                                    ))}
                                    {externalPbxLeadHeaders.length === 0 && (
                                        <p className="text-xs text-muted-foreground">
                                            Only the identity fields needed to transfer or hang up the call are captured.
                                        </p>
                                    )}
                                    {!externalPbxLeadHeadersValid && (
                                        <p className="text-xs text-destructive">
                                            Each lead field must start with a letter and contain only letters, numbers, and underscores.
                                        </p>
                                    )}
                                </div>
                            </div>
                        </div>
                    </SettingBlock>
                )}
            </SettingsSection>
        </>
    );
}

// ---------------------------------------------------------------------------
// Section: Template variables
// ---------------------------------------------------------------------------

function TemplateVariablesSection({
    templateContextVariables,
    onSave,
}: {
    templateContextVariables: Record<string, string>;
    onSave: (variables: Record<string, string>) => Promise<void>;
}) {
    const [contextVars, setContextVars] = useState<Record<string, string>>(templateContextVariables);
    const [newKey, setNewKey] = useState("");
    const [newValue, setNewValue] = useState("");

    // A filled-in "add" row counts as a change, and is saved with the rest.
    const pendingVars = newKey.trim() && newValue ? { ...contextVars, [newKey.trim()]: newValue } : contextVars;
    // A half-filled add row is a change too, so it isn't silently dropped.
    const halfFilled = Boolean(newKey.trim()) !== Boolean(newValue);
    const isDirty = halfFilled || JSON.stringify(pendingVars) !== JSON.stringify(templateContextVariables);

    useUnsavedChanges("variables", isDirty);
    useSettingsSection("variables", {
        label: "Variables",
        dirty: isDirty,
        blocker: !halfFilled ? null : newValue ? "Give the new variable a name" : "Give the new variable a value",
        save: () => onSave(pendingVars),
        afterSave: () => {
            setContextVars(pendingVars);
            setNewKey("");
            setNewValue("");
        },
    });

    const handleAdd = () => {
        if (!newKey.trim() || !newValue) return;
        setContextVars((prev) => ({ ...prev, [newKey.trim()]: newValue }));
        setNewKey("");
        setNewValue("");
    };

    const handleRemove = (key: string) => {
        setContextVars((prev) => {
            const next = { ...prev };
            delete next[key];
            return next;
        });
    };

    const entries = Object.entries(contextVars);
    const columns = "grid grid-cols-[minmax(0,180px)_minmax(0,1fr)_36px] items-center gap-3 px-[18px]";

    return (
        <SettingsSection
            id="variables"
            icon={Variable}
            tone="sky"
            title="Variables"
            description={
                <>
                    Values prompts can use as <code className="font-mono text-[11.5px] text-ink-2">{"{{name}}"}</code>.
                    Campaigns and the API can override them per call.
                </>
            }
        >
            <div>
                <div
                    aria-hidden
                    className={`${columns} bg-panel-2 py-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-3`}
                >
                    <span>Name</span>
                    <span>Default value</span>
                    <span />
                </div>
                {entries.map(([key, value]) => (
                    <div key={key} className={`${columns} border-t border-line-soft py-2`}>
                        <span className="truncate font-mono text-[12.5px] text-foreground" title={key}>
                            {key}
                        </span>
                        <Input
                            aria-label={`Default value for ${key}`}
                            value={value}
                            onChange={(e) => setContextVars((prev) => ({ ...prev, [key]: e.target.value }))}
                            className="h-8"
                        />
                        <Button
                            size="icon"
                            variant="ghost"
                            onClick={() => handleRemove(key)}
                            aria-label={`Remove ${key}`}
                            className="size-8 text-ink-3 hover:text-danger"
                        >
                            <Trash2Icon className="h-4 w-4" />
                        </Button>
                    </div>
                ))}
                <div className={`${columns} border-t border-line-soft py-2`}>
                    <Input
                        aria-label="New variable name"
                        placeholder="new_variable"
                        value={newKey}
                        onChange={(e) => setNewKey(e.target.value)}
                        className="h-8 font-mono text-[12.5px]"
                    />
                    <Input
                        aria-label="New variable value"
                        placeholder="Default value"
                        value={newValue}
                        onChange={(e) => setNewValue(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") handleAdd();
                        }}
                        className="h-8"
                    />
                    <Button
                        size="icon"
                        variant="outline"
                        onClick={handleAdd}
                        disabled={!newKey.trim() || !newValue}
                        aria-label="Add variable"
                        className="size-8"
                    >
                        <Plus className="h-4 w-4" />
                    </Button>
                </div>
            </div>
        </SettingsSection>
    );
}

// ---------------------------------------------------------------------------
// Section: Dictionary
// ---------------------------------------------------------------------------

function DictionarySection({
    dictionary,
    onSave,
}: {
    dictionary: string;
    onSave: (dictionary: string) => Promise<void>;
}) {
    const [dictionaryValue, setDictionaryValue] = useState(dictionary);
    const isDirty = dictionaryValue !== dictionary;

    useUnsavedChanges("dictionary", isDirty);
    useSettingsSection("dictionary", {
        label: "Dictionary",
        dirty: isDirty,
        blocker: null,
        save: () => onSave(dictionaryValue),
    });

    return (
        <SettingsSection
            id="dictionary"
            icon={BookA}
            tone="amber"
            title="Dictionary"
            description="Names and terms the transcriber should listen for. May cost extra with some providers."
        >
            <SettingBlock>
                <Label htmlFor="dictionary-terms" className="sr-only">Dictionary terms</Label>
                <Textarea
                    id="dictionary-terms"
                    placeholder="Words separated by commas, e.g. billing department, tretinoin"
                    value={dictionaryValue}
                    onChange={(e) => setDictionaryValue(e.target.value)}
                    rows={4}
                    className="resize-y font-mono text-[13px]"
                />
            </SettingBlock>
        </SettingsSection>
    );
}

// ---------------------------------------------------------------------------
// Section: Voicemail and screening
// ---------------------------------------------------------------------------

function VoicemailSection({
    workflowConfigurations,
    defaultAnswerClassifierPrompt,
}: {
    workflowConfigurations: WorkflowConfigurations;
    defaultAnswerClassifierPrompt: string;
}) {
    const getConfig = (): VoicemailDetectionConfiguration => ({
        ...DEFAULT_VOICEMAIL_DETECTION_CONFIGURATION,
        ...workflowConfigurations.voicemail_detection,
    });

    const [enabled, setEnabled] = useState(getConfig().enabled);
    const [useWorkflowLlm, setUseWorkflowLlm] = useState(getConfig().use_workflow_llm);
    const platformModels = Boolean(useAppConfig().config?.platformModelsEnabled);
    const [provider, setProvider] = useState(getConfig().provider || "openai");
    const [model, setModel] = useState(getConfig().model || "gpt-4.1");
    const [apiKey, setApiKey] = useState(getConfig().api_key || "");
    const savedPrompt = getConfig().system_prompt;
    const [systemPrompt, setSystemPrompt] = useState(savedPrompt || "");
    const [promptEdited, setPromptEdited] = useState(false);

    // The defaults endpoint resolves after first paint. A workflow that saved its
    // own instructions keeps showing those; one that never did starts from the
    // built-in text so it can be edited rather than written from scratch.
    useEffect(() => {
        if (promptEdited) return;
        setSystemPrompt(savedPrompt || defaultAnswerClassifierPrompt);
    }, [defaultAnswerClassifierPrompt, promptEdited, savedPrompt]);
    const [answerSettings, setAnswerSettings] = useState(readAnswerSupervisorSettings(getConfig()));

    const isDirty = useMemo(() => {
        const init = {
            ...DEFAULT_VOICEMAIL_DETECTION_CONFIGURATION,
            ...workflowConfigurations.voicemail_detection,
        };
        return (
            enabled !== init.enabled ||
            useWorkflowLlm !== init.use_workflow_llm ||
            provider !== (init.provider || "openai") ||
            model !== (init.model || "gpt-4.1") ||
            apiKey !== (init.api_key || "") ||
            // Showing the built-in text is not a change; editing it is. Match the
            // prefill's truthiness test, or a stored "" reads as dirty on load.
            systemPrompt !== (init.system_prompt || defaultAnswerClassifierPrompt) ||
            JSON.stringify(answerSettings) !== JSON.stringify(readAnswerSupervisorSettings(init))
        );
    }, [enabled, useWorkflowLlm, provider, model, apiKey, systemPrompt, defaultAnswerClassifierPrompt, answerSettings, workflowConfigurations]);

    useUnsavedChanges("voicemail", isDirty);

    const buildVoicemailConfig = (): VoicemailDetectionConfiguration => ({
        ...answerSettings,
        enabled,
        // Platform models classify with the agent's model; never send a key.
        use_workflow_llm: platformModels || useWorkflowLlm,
        provider: platformModels || useWorkflowLlm ? undefined : provider,
        model: platformModels || useWorkflowLlm ? undefined : model,
        api_key: platformModels || useWorkflowLlm ? undefined : apiKey,
        // Persist only instructions that differ from the built-in text, so a
        // workflow that never customized them keeps following platform updates
        // instead of freezing today's copy. Clearing the box reverts to them.
        system_prompt:
            systemPrompt.trim() &&
                systemPrompt.trim() !== defaultAnswerClassifierPrompt.trim()
                ? systemPrompt.trim()
                : undefined,
    });

    useSettingsSection("voicemail", {
        label: "Voicemail and screening",
        dirty: isDirty,
        blocker: enabled && isVoicemailMessageMissing(answerSettings) ? "Add the voicemail message" : null,
        patch: () => ({ configurations: { voicemail_detection: buildVoicemailConfig() } }),
        afterSave: () => {
            setSystemPrompt(buildVoicemailConfig().system_prompt || defaultAnswerClassifierPrompt);
            setPromptEdited(false);
        },
    });

    return (
        <SettingsSection
            id="voicemail"
            icon={PhoneOff}
            title="Voicemail and screening"
            description="What the agent does when a machine or call screener answers. Outbound calls with separate speech and language models; not realtime speech-to-speech yet."
        >
            <SettingRow
                compact
                label="Handle voicemail and screening"
                htmlFor="voicemail-enabled"
                hint="Detects voicemail, screening services and phone menus before the agent talks."
            >
                <Switch id="voicemail-enabled" checked={enabled} onCheckedChange={setEnabled} />
            </SettingRow>
            {enabled && (
                <SettingBlock>
                        <AnswerSupervisorFields value={answerSettings} onChange={setAnswerSettings} />
                        <details className="rounded-md border p-3">
                            <summary className="cursor-pointer text-sm font-medium">Classification model</summary>
                            <div className="mt-3 space-y-3">
                                {platformModels ? (
                                    <p className="text-xs text-muted-foreground">
                                        Classification uses this agent&apos;s language model.
                                    </p>
                                ) : (
                                    <div className="flex items-center space-x-2 rounded-md border bg-muted/20 p-2">
                                        <Switch
                                            id="voicemail-use-workflow-llm"
                                            checked={useWorkflowLlm}
                                            onCheckedChange={setUseWorkflowLlm}
                                        />
                                        <Label htmlFor="voicemail-use-workflow-llm">Use the agent&apos;s LLM</Label>
                                        <Label className="ml-2 text-xs text-muted-foreground">
                                            Use the LLM configured in your account settings.
                                        </Label>
                                    </div>
                                )}

                                {!platformModels && !useWorkflowLlm && (
                                    <LLMConfigSelector
                                        provider={provider}
                                        onProviderChange={setProvider}
                                        model={model}
                                        onModelChange={setModel}
                                        apiKey={apiKey}
                                        onApiKeyChange={setApiKey}
                                    />
                                )}

                                <div className="space-y-2">
                                    <Label htmlFor="voicemail-system-prompt">Classifier instructions</Label>
                                    <Textarea
                                        id="voicemail-system-prompt"
                                        rows={6}
                                        maxLength={8000}
                                        value={systemPrompt}
                                        placeholder="Leave blank to use the built-in instructions."
                                        onChange={e => {
                                            setPromptEdited(true);
                                            setSystemPrompt(e.target.value);
                                        }}
                                    />
                                    <p className="text-xs text-muted-foreground">
                                        These instructions decide whether the answering party is a person, a
                                        voicemail, a screening service or an IVR menu. Edit them when your
                                        calls are not in English: describe the greetings and carrier
                                        announcements your callers actually hear. Leave them unchanged to
                                        keep following the built-in instructions as they improve; clear the
                                        box to go back to them. The reply must be a single label —
                                        CONVERSATION, VOICEMAIL, NO_MESSAGE, SCREENER, SCREENING_WAIT, IVR
                                        or UNKNOWN. Anything else is read as UNKNOWN, which lets the call
                                        through to the agent, so instructions that only answer CONVERSATION
                                        or VOICEMAIL will silently disable screening and IVR handling.
                                    </p>
                                </div>
                            </div>
                        </details>
                </SettingBlock>
            )}
        </SettingsSection>
    );
}

// ---------------------------------------------------------------------------
// Section: Agent UUID
// ---------------------------------------------------------------------------

function AgentUuidSection({ workflowUuid }: { workflowUuid: string }) {
    const handleCopy = async () => {
        try {
            await copyTextToClipboard(workflowUuid);
            toast.success("Agent UUID copied");
        } catch {
            toast.error("Failed to copy Agent UUID");
        }
    };

    return (
        <SettingsSection id="identity" icon={Fingerprint} title="Identity" description="Stable identifiers for integrations.">
            <SettingRow label="Agent UUID" hint="Used in agent-stream URLs and anywhere a numeric ID isn't portable.">
                <button
                    type="button"
                    onClick={handleCopy}
                    aria-label="Copy agent UUID"
                    className="group flex w-full items-center gap-2 rounded-md border border-line bg-panel-2 px-2.5 py-2 text-left font-mono text-xs transition-colors hover:bg-panel"
                >
                    <code className="flex-1 truncate">{workflowUuid}</code>
                    <Clipboard className="h-3.5 w-3.5 shrink-0 text-ink-3 transition-colors group-hover:text-foreground" />
                </button>
            </SettingRow>
        </SettingsSection>
    );
}

// ---------------------------------------------------------------------------
// Page — "Advanced settings"
// ---------------------------------------------------------------------------

/**
 * Everything about an agent that does not have a home of its own in the nav.
 *
 * The design canvas (app-doc/claude-design/Failte AI v2.dc.html) gives each
 * agent concern its own nav row; the sections here are the remainder — call
 * behaviour, template variables, the pronunciation dictionary, voicemail
 * detection, the report export and the agent's identifiers. Model overrides
 * and the website widget moved out to "Model and voice" and "Deployment".
 *
 * The header, the nav panel and the test rail belong to the shell, so this
 * screen is only its own content plus the on-this-page rail.
 */
export default function AgentAdvancedSettingsPage() {
    return (
        <AgentSectionShell>
            {(context) => <AdvancedSettings context={context} />}
        </AgentSectionShell>
    );
}

function AdvancedSettings({ context }: { context: AgentSectionContext }) {
    const {
        workflow,
        workflowId,
        workflowName,
        workflowConfigurations,
        defaultCallDispositions,
        defaultAnswerClassifierPrompt,
        templateContextVariables,
        dictionary,
        saveWorkflowConfigurations,
        saveTemplateContextVariables,
        saveDictionary,
    } = context;
    const { dirtySections } = useUnsavedChangesContext();
    const [activeSection, setActiveSection] = useState("general");
    // Discard remounts the sections, so every form goes back to what is saved.
    const [formKey, setFormKey] = useState(0);

    // Intersection observer for the active on-this-page link.
    useEffect(() => {
        const ids = NAV_ITEMS.map((n) => n.id);
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        setActiveSection(entry.target.id);
                        break;
                    }
                }
            },
            { rootMargin: "-20% 0px -60% 0px" },
        );
        ids.forEach((id) => {
            const el = document.getElementById(id);
            if (el) observer.observe(el);
        });
        return () => observer.disconnect();
        // Discard remounts the sections, so observe the new elements.
    }, [formKey]);

    const navItems = NAV_ITEMS.filter((item) => item.id !== "identity" || workflow.workflow_uuid);

    return (
        <SettingsSaveProvider
            workflowName={workflowName}
            workflowConfigurations={workflowConfigurations}
            saveWorkflowConfigurations={saveWorkflowConfigurations}
            onDiscard={() => setFormKey((key) => key + 1)}
            savedMessage={`Settings saved. ${PUBLISH_WORKFLOW_REMINDER}`}
        >
            <div className="page-body @container">
                <header className="mb-5 flex flex-col gap-1">
                    <h1 className="text-xl font-bold tracking-[-0.01em] text-foreground">Advanced settings</h1>
                    <p className="text-[13.5px] text-ink-2">
                        Behaviour, variables, dictionary and diagnostics for this agent. Changes apply once you publish.
                    </p>
                </header>
                <div className="flex gap-7">
                    <nav aria-label="Sections" className="hidden w-48 shrink-0 @4xl:block">
                        <div className="sticky top-4 flex flex-col gap-0.5">
                            {navItems.map((item) => (
                                <a
                                    key={item.id}
                                    href={`#${item.id}`}
                                    aria-current={activeSection === item.id ? "true" : undefined}
                                    className={cn(
                                        "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors hover:text-foreground",
                                        activeSection === item.id
                                            ? "bg-panel-2 font-semibold text-foreground"
                                            : "font-medium text-ink-2",
                                    )}
                                >
                                    {item.label}
                                    {dirtySections.has(item.id) && (
                                        <span
                                            role="img"
                                            aria-label="Unsaved changes"
                                            className="ml-auto size-1.5 rounded-full bg-amber"
                                        />
                                    )}
                                </a>
                            ))}
                        </div>
                    </nav>
                    <div key={formKey} className="flex min-w-0 max-w-[820px] flex-1 flex-col gap-[18px] pb-20">
                        <GeneralSection
                            workflowConfigurations={workflowConfigurations}
                            defaultCallDispositions={defaultCallDispositions}
                            workflowName={workflowName}
                            workflowId={workflowId}
                        />

                        <TemplateVariablesSection
                            templateContextVariables={templateContextVariables}
                            onSave={saveTemplateContextVariables}
                        />

                        <DictionarySection dictionary={dictionary} onSave={saveDictionary} />

                        <VoicemailSection
                            defaultAnswerClassifierPrompt={defaultAnswerClassifierPrompt}
                            workflowConfigurations={workflowConfigurations}
                        />

                        {workflow.workflow_uuid && <AgentUuidSection workflowUuid={workflow.workflow_uuid} />}

                        <SettingsSection
                            id="recordings"
                            icon={Mic}
                            title="Recordings"
                            description={
                                <>
                                    Shared by every agent in the workspace. Type{" "}
                                    <code className="font-mono text-[11.5px] text-ink-2">@</code> in a prompt to insert one.
                                </>
                            }
                            action={
                                <Button variant="outline" size="sm" asChild>
                                    <Link href="/recordings">
                                        Open recordings
                                        <ExternalLink className="h-3.5 w-3.5" />
                                    </Link>
                                </Button>
                            }
                        />

                        <ReportSection workflowId={workflowId} />
                    </div>
                </div>
            </div>
        </SettingsSaveProvider>
    );
}
