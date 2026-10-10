"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import type { EnumOption, FormErrors, FormValue, FormValues, SchemaField } from "./schemaForm";

interface ConfigSchemaFormProps {
    fields: SchemaField[];
    values: FormValues;
    errors: FormErrors;
    onChange: (key: string, value: FormValue) => void;
    disabled?: boolean;
    /** Prefix for input ids, so two forms on a page don't collide. */
    idPrefix?: string;
}

/**
 * Renders a provider's config fields. Required fields come first; the rest sit
 * under "More settings", since their defaults suit most workspaces.
 */
export function ConfigSchemaForm({
    fields,
    values,
    errors,
    onChange,
    disabled = false,
    idPrefix = "cfg",
}: ConfigSchemaFormProps) {
    const required = fields.filter((f) => f.required);
    const optional = fields.filter((f) => !f.required);
    const optionalHasError = optional.some((f) => errors[f.key]);
    const [showMore, setShowMore] = useState(false);

    const render = (field: SchemaField) => (
        <SchemaFieldInput
            key={field.key}
            field={field}
            value={values[field.key]}
            error={errors[field.key]}
            onChange={(value) => onChange(field.key, value)}
            disabled={disabled}
            id={`${idPrefix}-${field.key}`}
        />
    );

    if (fields.length === 0) return null;

    return (
        <div className="grid gap-4">
            {required.map(render)}
            {optional.length > 0 && (
                <Collapsible open={showMore || optionalHasError} onOpenChange={setShowMore}>
                    <CollapsibleTrigger className="flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-foreground">
                        <ChevronDown
                            className={cn("size-4 transition-transform", (showMore || optionalHasError) && "rotate-180")}
                            aria-hidden
                        />
                        More settings
                        <span className="font-normal text-ink-3">({optional.length})</span>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="mt-4 grid gap-4">{optional.map(render)}</CollapsibleContent>
                </Collapsible>
            )}
        </div>
    );
}

interface SchemaFieldInputProps {
    field: SchemaField;
    value: FormValue | undefined;
    error?: string;
    onChange: (value: FormValue) => void;
    disabled: boolean;
    id: string;
}

function SchemaFieldInput({ field, value, error, onChange, disabled, id }: SchemaFieldInputProps) {
    const isList = field.kind === "string_array" || field.kind === "integer_array";
    const hint = [field.description, isList ? "Separate values with commas." : null].filter(Boolean).join(" ");
    const describedBy = [hint ? `${id}-desc` : null, error ? `${id}-error` : null]
        .filter(Boolean)
        .join(" ") || undefined;
    const label = (
        <>
            {field.label}
            {field.required && <span className="text-danger"> *</span>}
        </>
    );
    const hints = (
        <>
            {hint && (
                <p id={`${id}-desc`} className="text-xs text-muted-foreground">
                    {hint}
                </p>
            )}
            {error && (
                <p id={`${id}-error`} className="text-xs text-destructive" role="alert">
                    {error}
                </p>
            )}
        </>
    );

    if (field.kind === "boolean") {
        return (
            <div className="grid gap-1.5">
                <div className="flex items-center justify-between gap-4">
                    <Label htmlFor={id}>{label}</Label>
                    <Switch
                        id={id}
                        checked={value === true}
                        onCheckedChange={(checked) => onChange(checked)}
                        disabled={disabled}
                        aria-describedby={describedBy}
                    />
                </div>
                {hints}
            </div>
        );
    }

    if (field.kind === "enum") {
        const current = typeof value === "string" ? value : "";
        return (
            <div className="grid gap-1.5">
                <Label htmlFor={id}>{label}</Label>
                <Select value={current} onValueChange={(v) => onChange(v)} disabled={disabled}>
                    <SelectTrigger id={id} aria-describedby={describedBy} aria-invalid={Boolean(error)}>
                        <SelectValue placeholder="Choose…" />
                    </SelectTrigger>
                    <SelectContent>
                        {(field.options ?? []).map((option) => (
                            <SelectItem key={String(option)} value={String(option)}>
                                {String(option)}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                {hints}
            </div>
        );
    }

    if (field.kind === "enum_array") {
        const selected: EnumOption[] = Array.isArray(value) ? value : [];
        const toggle = (option: EnumOption, checked: boolean) => {
            const next = checked
                ? [...selected, option]
                : selected.filter((o) => o !== option);
            // Keep the schema's option order.
            onChange((field.options ?? []).filter((o) => next.includes(o)));
        };
        return (
            <fieldset className="grid gap-1.5" aria-describedby={describedBy}>
                <legend className="mb-1 text-sm font-medium">{label}</legend>
                <div className="flex flex-wrap gap-x-4 gap-y-2">
                    {(field.options ?? []).map((option) => {
                        const optionId = `${id}-${String(option)}`;
                        return (
                            <div key={String(option)} className="flex items-center gap-2">
                                <Checkbox
                                    id={optionId}
                                    checked={selected.includes(option)}
                                    onCheckedChange={(checked) => toggle(option, checked === true)}
                                    disabled={disabled}
                                />
                                <Label htmlFor={optionId} className="font-normal">
                                    {String(option)}
                                </Label>
                            </div>
                        );
                    })}
                </div>
                {hints}
            </fieldset>
        );
    }

    const numeric = field.kind === "integer" || field.kind === "number";
    return (
        <div className="grid gap-1.5">
            <Label htmlFor={id}>{label}</Label>
            <Input
                id={id}
                type={numeric ? "number" : "text"}
                inputMode={numeric ? "numeric" : undefined}
                min={numeric ? field.minimum : undefined}
                max={numeric ? field.maximum : undefined}
                step={field.kind === "integer" ? 1 : undefined}
                maxLength={field.kind === "string" ? field.maxLength : undefined}
                value={typeof value === "string" ? value : ""}
                onChange={(e) => onChange(e.target.value)}
                disabled={disabled}
                required={field.required}
                aria-invalid={Boolean(error)}
                aria-describedby={describedBy}
                placeholder={field.nullable && !field.required ? "Not set" : undefined}
            />
            {hints}
        </div>
    );
}
