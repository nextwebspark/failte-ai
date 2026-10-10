"use client";

import { useState } from "react";

import type { ToolResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { MarkdownPreview } from "../MarkdownPreview";
import {
    BODY_MAX_BYTES,
    byteLength,
    CATEGORY_MAX,
    categoryError,
    DESCRIPTION_MAX,
    type DraftErrors,
    formatBytes,
    NAME_MAX,
} from "../validation";
import { AllowedToolsPicker } from "./AllowedToolsPicker";
import type { EditorDraft } from "./editorModel";
import { FilesEditor } from "./FilesEditor";

export interface NameConflict {
    message: string;
    suggestedName: string | null;
}

interface SkillEditorFormProps {
    mode: "workspace" | "library";
    draft: EditorDraft;
    onChange: (draft: EditorDraft) => void;
    errors: DraftErrors;
    /** Only show field errors once the user has touched or tried to save. */
    showErrors: boolean;
    readOnly: boolean;
    tools: ToolResponse[];
    /** Why the tool list couldn't be loaded, if it couldn't. */
    toolsError?: string | null;
    nameConflict: NameConflict | null;
}

function Counter({ value, max, id }: { value: number; max: number; id: string }) {
    return (
        <span id={id} className={cn("font-mono text-[11px]", value > max ? "text-destructive" : "text-ink-3")}>
            {value}/{max}
        </span>
    );
}

function FieldError({ id, message }: { id: string; message: string | null }) {
    if (!message) return null;
    return (
        <p id={id} className="text-xs text-destructive">
            {message}
        </p>
    );
}

export function SkillEditorForm({
    mode,
    draft,
    onChange,
    errors,
    showErrors,
    readOnly,
    tools,
    toolsError = null,
    nameConflict,
}: SkillEditorFormProps) {
    const [preview, setPreview] = useState(readOnly);
    const set = <K extends keyof EditorDraft>(key: K, value: EditorDraft[K]) => onChange({ ...draft, [key]: value });

    // Errors show as soon as a field has content, or for every field after a save attempt.
    const nameProblem = showErrors || draft.name ? errors.name : null;
    const descriptionProblem = showErrors || draft.description ? errors.description : null;
    const bodyProblem = showErrors || draft.body_md ? errors.body : null;
    const bodyBytes = byteLength(draft.body_md);
    const categoryProblem = mode === "library" ? categoryError(draft.category) : null;

    return (
        <div className="space-y-6">
            <Panel className="space-y-5">
                <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                        <Label htmlFor="skill-name">Name</Label>
                        <Counter id="skill-name-count" value={draft.name.length} max={NAME_MAX} />
                    </div>
                    <Input
                        id="skill-name"
                        value={draft.name}
                        readOnly={readOnly}
                        onChange={(event) => set("name", event.target.value)}
                        placeholder="returns-policy"
                        className="font-mono"
                        autoComplete="off"
                        spellCheck={false}
                        aria-invalid={Boolean(nameProblem || nameConflict)}
                        aria-describedby="skill-name-hint skill-name-error skill-name-count"
                    />
                    <p id="skill-name-hint" className="text-xs text-muted-foreground">
                        Lowercase letters, digits and hyphens. The agent sees this name in its list of skills.
                    </p>
                    <FieldError id="skill-name-error" message={nameProblem} />
                    {nameConflict && (
                        <div className="flex flex-wrap items-center gap-2" role="alert">
                            <p className="text-xs text-destructive">{nameConflict.message}</p>
                            {nameConflict.suggestedName && !readOnly && (
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="soft"
                                    onClick={() => set("name", nameConflict.suggestedName ?? draft.name)}
                                >
                                    Use {nameConflict.suggestedName}
                                </Button>
                            )}
                        </div>
                    )}
                </div>

                <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                        <Label htmlFor="skill-description">Description</Label>
                        <Counter id="skill-description-count" value={draft.description.length} max={DESCRIPTION_MAX} />
                    </div>
                    <Textarea
                        id="skill-description"
                        value={draft.description}
                        readOnly={readOnly}
                        rows={3}
                        // Single line: the description is injected into prompts and frontmatter.
                        onChange={(event) => set("description", event.target.value.replace(/[\r\n]+/g, " "))}
                        onKeyDown={(event) => {
                            if (event.key === "Enter") event.preventDefault();
                        }}
                        placeholder="Use when the caller asks to return or exchange an item."
                        className="min-h-0 resize-none"
                        aria-invalid={Boolean(descriptionProblem)}
                        aria-describedby="skill-description-hint skill-description-error skill-description-count"
                    />
                    <p id="skill-description-hint" className="text-xs text-muted-foreground">
                        One line that tells the agent when to load this skill. It is always in the agent&apos;s
                        prompt, so keep it short.
                    </p>
                    <FieldError id="skill-description-error" message={descriptionProblem} />
                </div>

                {mode === "library" && (
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                            <Label htmlFor="skill-category">Category</Label>
                            <Counter id="skill-category-count" value={draft.category.trim().length} max={CATEGORY_MAX} />
                        </div>
                        <Input
                            id="skill-category"
                            value={draft.category}
                            readOnly={readOnly}
                            onChange={(event) => set("category", event.target.value)}
                            placeholder="customer-service"
                            aria-invalid={Boolean(categoryProblem)}
                            aria-describedby="skill-category-error"
                        />
                        <FieldError id="skill-category-error" message={categoryProblem} />
                    </div>
                )}
            </Panel>

            <Panel className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <h3 className="text-sm font-medium" id="skill-body-label">
                            Instructions (SKILL.md)
                        </h3>
                        <p className="text-xs text-muted-foreground">
                            The playbook the agent follows once it loads this skill. Markdown is supported.
                        </p>
                    </div>
                    <div className="inline-flex rounded-md border border-line p-0.5" role="group" aria-label="Instructions view">
                        {!readOnly && (
                            <Button
                                type="button"
                                size="sm"
                                variant={preview ? "ghost" : "secondary"}
                                aria-pressed={!preview}
                                onClick={() => setPreview(false)}
                                className="h-7"
                            >
                                Write
                            </Button>
                        )}
                        <Button
                            type="button"
                            size="sm"
                            variant={preview ? "secondary" : "ghost"}
                            aria-pressed={preview}
                            onClick={() => setPreview(true)}
                            className="h-7"
                        >
                            Preview
                        </Button>
                        {readOnly && (
                            <Button
                                type="button"
                                size="sm"
                                variant={preview ? "ghost" : "secondary"}
                                aria-pressed={!preview}
                                onClick={() => setPreview(false)}
                                className="h-7"
                            >
                                Source
                            </Button>
                        )}
                    </div>
                </div>
                {preview ? (
                    <div className="min-h-[200px] rounded-md border border-line bg-background p-4" aria-labelledby="skill-body-label">
                        <MarkdownPreview source={draft.body_md} />
                    </div>
                ) : (
                    <Textarea
                        id="skill-body"
                        value={draft.body_md}
                        readOnly={readOnly}
                        onChange={(event) => set("body_md", event.target.value)}
                        className="min-h-[360px] font-mono text-xs leading-relaxed"
                        spellCheck={false}
                        aria-labelledby="skill-body-label"
                        aria-invalid={Boolean(bodyProblem)}
                        aria-describedby="skill-body-error skill-body-size"
                    />
                )}
                <div className="flex items-start justify-between gap-2">
                    <FieldError id="skill-body-error" message={bodyProblem} />
                    <span
                        id="skill-body-size"
                        className={cn(
                            "ml-auto font-mono text-[11px]",
                            bodyBytes > BODY_MAX_BYTES ? "text-destructive" : "text-ink-3",
                        )}
                    >
                        {formatBytes(bodyBytes)} / {BODY_MAX_BYTES / 1024} KB
                    </span>
                </div>
            </Panel>

            <Panel>
                <FilesEditor
                    files={draft.files}
                    onChange={(files) => set("files", files)}
                    issues={errors.files}
                    readOnly={readOnly}
                />
            </Panel>

            {mode === "workspace" && (
                <Panel>
                    <AllowedToolsPicker
                        value={draft.allowed_tool_uuids}
                        onChange={(value) => set("allowed_tool_uuids", value)}
                        tools={tools}
                        toolsError={toolsError}
                        disabled={readOnly}
                    />
                </Panel>
            )}
        </div>
    );
}
