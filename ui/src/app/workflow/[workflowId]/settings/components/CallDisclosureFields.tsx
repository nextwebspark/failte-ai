import { useEffect, useState } from "react";

import { listRecordingsApiV1WorkflowRecordingsGet } from "@/client/sdk.gen";
import type { RecordingResponseSchema } from "@/client/types.gen";
import { RecordingSelect } from "@/components/flow/TextOrAudioInput";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import {
    type CallDisclosureConfiguration,
    DEFAULT_CALL_DISCLOSURE_TEXT,
    MAX_CALL_DISCLOSURE_TEXT_LENGTH,
} from "@/types/workflow-configurations";

/** Why the disclosure can't be saved as it is, or null when it can. */
export function callDisclosureProblem(value: CallDisclosureConfiguration): string | null {
    if (!value.enabled) return null;
    if (value.text.length > MAX_CALL_DISCLOSURE_TEXT_LENGTH) {
        return `Shorten the AI disclosure to ${MAX_CALL_DISCLOSURE_TEXT_LENGTH} characters`;
    }
    if (value.type === "audio" && !value.recording_id) return "Choose the AI disclosure recording";
    if (!value.text.trim() && value.type === "text") return "Add the AI disclosure text";
    return null;
}

/**
 * The text and optional recording of the AI and recording notice. The switch
 * that turns it on lives in the settings row above; this renders only while
 * it is on.
 */
export function CallDisclosureFields({
    value,
    onChange,
}: {
    value: CallDisclosureConfiguration;
    onChange: (value: CallDisclosureConfiguration) => void;
}) {
    const { user, loading: authLoading } = useAuth();
    const [recordings, setRecordings] = useState<RecordingResponseSchema[]>([]);
    const [error, setError] = useState("");
    const wantsRecordings = value.type === "audio";

    useEffect(() => {
        if (!wantsRecordings || authLoading || !user) return;
        let cancelled = false;
        setError("");
        listRecordingsApiV1WorkflowRecordingsGet({ query: {} }).then((response) => {
            if (cancelled) return;
            if (response.error || !response.data) {
                setError(detailFromError(response.error, "Could not load recordings."));
                return;
            }
            setRecordings(response.data.recordings);
        }).catch(() => {
            if (!cancelled) setError("Could not load recordings.");
        });
        return () => { cancelled = true; };
    }, [wantsRecordings, authLoading, user]);

    // The setting stores the human-readable recording ID; the picker works in
    // primary keys, so translate at the boundary.
    const selectedPk = recordings.find((r) => r.recording_id === value.recording_id)?.id;
    const problem = callDisclosureProblem(value);

    return (
        <div className="space-y-3">
            <div className="space-y-1.5">
                <Label htmlFor="call-disclosure-text" className="text-xs">What the agent says first</Label>
                <Textarea
                    id="call-disclosure-text"
                    rows={2}
                    maxLength={MAX_CALL_DISCLOSURE_TEXT_LENGTH}
                    value={value.text}
                    placeholder={DEFAULT_CALL_DISCLOSURE_TEXT}
                    onChange={(e) => onChange({ ...value, text: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                    Played before the greeting on every call. Supports {"{{variables}}"}. Speech-to-speech
                    models say it as the start of their opening line.
                </p>
            </div>
            <div className="space-y-2">
                <Label id="call-disclosure-format" className="text-xs">Play it as</Label>
                <RadioGroup
                    aria-labelledby="call-disclosure-format"
                    value={value.type}
                    onValueChange={(type) => {
                        if (type === "text" || type === "audio") onChange({ ...value, type });
                    }}
                    className="flex items-center gap-4"
                >
                    <div className="flex items-center gap-2">
                        <RadioGroupItem value="text" id="call-disclosure-format-text" />
                        <Label htmlFor="call-disclosure-format-text" className="font-normal cursor-pointer">
                            The agent&apos;s voice
                        </Label>
                    </div>
                    <div className="flex items-center gap-2">
                        <RadioGroupItem value="audio" id="call-disclosure-format-audio" />
                        <Label htmlFor="call-disclosure-format-audio" className="font-normal cursor-pointer">
                            A recording
                        </Label>
                    </div>
                </RadioGroup>
                {value.type === "audio" && (
                    <>
                        <RecordingSelect
                            value={selectedPk ? String(selectedPk) : ""}
                            recordings={recordings}
                            onChange={(pk) =>
                                onChange({
                                    ...value,
                                    recording_id: recordings.find((r) => String(r.id) === pk)?.recording_id ?? null,
                                })
                            }
                        />
                        <p className="text-xs text-muted-foreground">
                            If the recording can&apos;t be played, and in text chat, the agent says the text above instead.
                        </p>
                    </>
                )}
            </div>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}
        </div>
    );
}
