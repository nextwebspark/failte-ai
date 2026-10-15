"use client";

import { FilePlus, FileText, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { byteLength, type FileIssue, formatBytes, MAX_FILES, pathError } from "../validation";
import { type EditorFile, newFileId } from "./editorModel";

interface FilesEditorProps {
    files: EditorFile[];
    onChange: (files: EditorFile[]) => void;
    issues: FileIssue[];
    readOnly: boolean;
}

/**
 * Reference files the agent can read on demand (`read_skill_file`): a flat
 * list of paths with a text editor for the selected one. Renaming is editing
 * the path; paths are checked as you type.
 */
export function FilesEditor({ files, onChange, issues, readOnly }: FilesEditorProps) {
    const [selectedId, setSelectedId] = useState<string | null>(files[0]?.id ?? null);
    const [newPath, setNewPath] = useState("");
    const [adding, setAdding] = useState(false);

    const selected = files.find((f) => f.id === selectedId) ?? files[0] ?? null;
    const selectedIndex = selected ? files.indexOf(selected) : -1;
    const issuesFor = (index: number) => issues.filter((i) => i.index === index).map((i) => i.message);
    const setIssues = issues.filter((i) => i.index === null).map((i) => i.message);
    const duplicate = files.some((f) => f.path.toLowerCase() === newPath.trim().toLowerCase());
    const newPathProblem = newPath.trim() ? (duplicate ? "Another file already uses this path" : pathError(newPath.trim())) : null;

    const update = (id: string, patch: Partial<EditorFile>) =>
        onChange(files.map((f) => (f.id === id ? { ...f, ...patch } : f)));

    const addFile = () => {
        const path = newPath.trim();
        if (!path || newPathProblem) return;
        const file: EditorFile = { id: newFileId(), path, content: "" };
        onChange([...files, file]);
        setSelectedId(file.id);
        setNewPath("");
        setAdding(false);
    };

    const remove = (id: string) => {
        const next = files.filter((f) => f.id !== id);
        onChange(next);
        if (selectedId === id) setSelectedId(next[0]?.id ?? null);
    };

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h3 className="text-sm font-medium">Files</h3>
                    <p className="text-xs text-muted-foreground">
                        Optional reference text the agent reads only when the instructions point to it, e.g.
                        references/returns-policy.md. Up to {MAX_FILES} text files.
                    </p>
                </div>
                {!readOnly && !adding && files.length < MAX_FILES && (
                    <Button type="button" size="sm" variant="soft" onClick={() => setAdding(true)}>
                        <FilePlus aria-hidden />
                        Add file
                    </Button>
                )}
            </div>

            {adding && (
                <form
                    className="flex flex-col gap-2 sm:flex-row sm:items-start"
                    onSubmit={(event) => {
                        event.preventDefault();
                        addFile();
                    }}
                >
                    <div className="flex-1 space-y-1">
                        <Label htmlFor="new-file-path" className="sr-only">
                            New file path
                        </Label>
                        <Input
                            id="new-file-path"
                            autoFocus
                            value={newPath}
                            onChange={(event) => setNewPath(event.target.value)}
                            placeholder="references/notes.md"
                            className="font-mono text-sm"
                            aria-invalid={Boolean(newPathProblem)}
                            aria-describedby="new-file-path-error"
                        />
                        {newPathProblem && (
                            <p id="new-file-path-error" className="text-xs text-destructive">
                                {newPathProblem}
                            </p>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <Button type="submit" size="sm" disabled={!newPath.trim() || Boolean(newPathProblem)}>
                            Add
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                                setAdding(false);
                                setNewPath("");
                            }}
                        >
                            Cancel
                        </Button>
                    </div>
                </form>
            )}

            {setIssues.map((message) => (
                <p key={message} className="text-xs text-destructive" role="alert">
                    {message}
                </p>
            ))}

            {files.length === 0 ? (
                !adding && <p className="text-sm text-muted-foreground">No files.</p>
            ) : (
                <div className="grid gap-3 md:grid-cols-[minmax(0,220px)_1fr]">
                    <ul className="space-y-1" aria-label="Skill files">
                        {files.map((file, index) => {
                            const hasIssue = issuesFor(index).length > 0;
                            return (
                                <li key={file.id}>
                                    <button
                                        type="button"
                                        onClick={() => setSelectedId(file.id)}
                                        aria-current={selected?.id === file.id ? "true" : undefined}
                                        className={cn(
                                            "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left font-mono text-xs hover:bg-muted",
                                            selected?.id === file.id && "bg-muted font-semibold",
                                            hasIssue && "text-destructive",
                                        )}
                                    >
                                        <FileText className="size-3.5 shrink-0" aria-hidden />
                                        <span className="truncate">{file.path || "(no path)"}</span>
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                    {selected && (
                        <div className="min-w-0 space-y-2">
                            <div className="flex items-start gap-2">
                                <div className="flex-1 space-y-1">
                                    <Label htmlFor="file-path" className="text-xs">
                                        Path
                                    </Label>
                                    <Input
                                        id="file-path"
                                        value={selected.path}
                                        readOnly={readOnly}
                                        onChange={(event) => update(selected.id, { path: event.target.value })}
                                        className="font-mono text-sm"
                                        aria-invalid={issuesFor(selectedIndex).length > 0}
                                    />
                                </div>
                                {!readOnly && (
                                    <Button
                                        type="button"
                                        size="icon"
                                        variant="ghost"
                                        className="mt-5 text-destructive hover:text-destructive"
                                        onClick={() => remove(selected.id)}
                                        aria-label={`Delete ${selected.path || "file"}`}
                                    >
                                        <Trash2 aria-hidden />
                                    </Button>
                                )}
                            </div>
                            {issuesFor(selectedIndex).map((message) => (
                                <p key={message} className="text-xs text-destructive" role="alert">
                                    {message}
                                </p>
                            ))}
                            <Label htmlFor="file-content" className="sr-only">
                                Content of {selected.path}
                            </Label>
                            <Textarea
                                id="file-content"
                                value={selected.content}
                                readOnly={readOnly}
                                onChange={(event) => update(selected.id, { content: event.target.value })}
                                className="min-h-[220px] font-mono text-xs leading-relaxed"
                                spellCheck={false}
                            />
                            <p className="text-right font-mono text-[11px] text-ink-3">
                                {formatBytes(byteLength(selected.content))}
                            </p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
