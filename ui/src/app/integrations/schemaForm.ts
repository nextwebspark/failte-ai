/**
 * A small JSON Schema -> form model, for the per-connection config a catalog
 * provider publishes (`config_schema`, a Pydantic model's JSON Schema).
 *
 * Supported property shapes: string, integer, number, boolean, enum (string or
 * number), and arrays of strings or integers (edited as comma-separated text,
 * or as checkboxes when the items are an enum). `anyOf: [X, {type: "null"}]`
 * makes a field nullable. Local `$ref`s into `$defs` are resolved. Anything
 * else is left out of the form and keeps its server-side value.
 */

export type FieldKind =
    | "string"
    | "integer"
    | "number"
    | "boolean"
    | "enum"
    | "string_array"
    | "integer_array"
    | "enum_array";

export type EnumOption = string | number;

export interface SchemaField {
    key: string;
    label: string;
    description?: string;
    kind: FieldKind;
    required: boolean;
    /** An empty value is sent as null rather than left out. */
    nullable: boolean;
    /** For enum and enum_array fields. */
    options?: EnumOption[];
    default?: unknown;
    minimum?: number;
    maximum?: number;
    minLength?: number;
    maxLength?: number;
    minItems?: number;
}

/** Form state: text inputs hold strings, checkboxes booleans, multi-selects arrays. */
export type FormValue = string | boolean | EnumOption[];
export type FormValues = Record<string, FormValue>;
export type FormErrors = Record<string, string>;

type SchemaObject = Record<string, unknown>;

function isObject(value: unknown): value is SchemaObject {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNumber(value: unknown): number | undefined {
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function resolveRef(node: SchemaObject, root: SchemaObject): SchemaObject {
    const ref = node.$ref;
    if (typeof ref !== "string" || !ref.startsWith("#/")) return node;
    let target: unknown = root;
    for (const part of ref.slice(2).split("/")) {
        target = isObject(target) ? target[part] : undefined;
    }
    return isObject(target) ? { ...target, ...withoutRef(node) } : node;
}

function withoutRef(node: SchemaObject): SchemaObject {
    const rest: SchemaObject = { ...node };
    delete rest.$ref;
    return rest;
}

/** Unwraps `anyOf: [X, {type: "null"}]` into X plus a nullable flag. */
function unwrapNullable(node: SchemaObject, root: SchemaObject): { node: SchemaObject; nullable: boolean } {
    const variants = node.anyOf ?? node.oneOf;
    if (Array.isArray(variants)) {
        const nonNull = variants.filter((v) => !(isObject(v) && v.type === "null"));
        if (nonNull.length === 1 && isObject(nonNull[0]) && nonNull.length < variants.length) {
            const inner = resolveRef(nonNull[0], root);
            const merged: SchemaObject = { ...inner };
            for (const key of ["title", "description", "default"]) {
                if (key in node) merged[key] = node[key];
            }
            return { node: merged, nullable: true };
        }
    }
    if (Array.isArray(node.type)) {
        const types = node.type.filter((t) => t !== "null");
        if (types.length === 1) {
            return { node: { ...node, type: types[0] }, nullable: types.length < node.type.length };
        }
    }
    return { node, nullable: false };
}

function enumOptions(node: SchemaObject): EnumOption[] | undefined {
    if (!Array.isArray(node.enum)) {
        return "const" in node && (typeof node.const === "string" || typeof node.const === "number")
            ? [node.const]
            : undefined;
    }
    const options = node.enum.filter(
        (v): v is EnumOption => typeof v === "string" || typeof v === "number",
    );
    return options.length > 0 ? options : undefined;
}

/** "calendar_id" -> "Calendar ID". */
export function humanizeKey(key: string): string {
    const words = key.split(/[_\s-]+/).filter(Boolean);
    return words
        .map((word, i) => {
            const lower = word.toLowerCase();
            if (["id", "url", "uri", "api"].includes(lower)) return lower.toUpperCase();
            return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
        })
        .join(" ");
}

function fieldKind(node: SchemaObject, root: SchemaObject): { kind: FieldKind; options?: EnumOption[] } | null {
    const options = enumOptions(node);
    if (options) return { kind: "enum", options };
    switch (node.type) {
        case "string":
            return { kind: "string" };
        case "integer":
            return { kind: "integer" };
        case "number":
            return { kind: "number" };
        case "boolean":
            return { kind: "boolean" };
        case "array": {
            if (!isObject(node.items)) return null;
            const items = resolveRef(node.items, root);
            const itemOptions = enumOptions(items);
            if (itemOptions) return { kind: "enum_array", options: itemOptions };
            if (items.type === "string") return { kind: "string_array" };
            if (items.type === "integer") return { kind: "integer_array" };
            return null;
        }
        default:
            return null;
    }
}

/** The form fields for a provider's config schema, in schema order. */
export function fieldsFromSchema(schema: unknown): SchemaField[] {
    if (!isObject(schema)) return [];
    const root = schema;
    const top = resolveRef(schema, root);
    if (!isObject(top.properties)) return [];
    const required = new Set(
        Array.isArray(top.required) ? top.required.filter((k): k is string => typeof k === "string") : [],
    );

    const fields: SchemaField[] = [];
    for (const [key, raw] of Object.entries(top.properties)) {
        if (!isObject(raw)) continue;
        const { node, nullable } = unwrapNullable(resolveRef(raw, root), root);
        const kind = fieldKind(node, root);
        if (!kind) continue;
        const items = isObject(node.items) ? resolveRef(node.items, root) : undefined;
        fields.push({
            key,
            label: humanizeKey(key),
            description: typeof node.description === "string" ? node.description : undefined,
            kind: kind.kind,
            options: kind.options,
            required: required.has(key),
            nullable,
            default: node.default,
            minimum: asNumber(node.minimum) ?? asNumber(items?.minimum),
            maximum: asNumber(node.maximum) ?? asNumber(items?.maximum),
            minLength: asNumber(node.minLength),
            maxLength: asNumber(node.maxLength),
            minItems: asNumber(node.minItems),
        });
    }
    return fields;
}

/** True when the schema has at least one required field. */
export function hasRequiredConfig(schema: unknown): boolean {
    return fieldsFromSchema(schema).some((f) => f.required);
}

function toFormValue(field: SchemaField, value: unknown): FormValue {
    switch (field.kind) {
        case "boolean":
            return value === true;
        case "enum_array":
            return Array.isArray(value)
                ? value.filter((v): v is EnumOption => typeof v === "string" || typeof v === "number")
                : [];
        case "string_array":
        case "integer_array":
            return Array.isArray(value) ? value.map(String).join(", ") : "";
        default:
            return value === null || value === undefined ? "" : String(value);
    }
}

/**
 * Starting values: the connection's current config where set, otherwise the
 * schema default, otherwise empty.
 */
export function initialValues(
    fields: SchemaField[],
    current?: Record<string, unknown> | null,
): FormValues {
    const values: FormValues = {};
    for (const field of fields) {
        const source = current && field.key in current ? current[field.key] : field.default;
        values[field.key] = toFormValue(field, source);
    }
    return values;
}

function parseInteger(text: string): number | null {
    return /^-?\d+$/.test(text) ? Number(text) : null;
}

function checkRange(field: SchemaField, n: number): string | null {
    if (field.minimum !== undefined && n < field.minimum) return `Must be at least ${field.minimum}`;
    if (field.maximum !== undefined && n > field.maximum) return `Must be at most ${field.maximum}`;
    return null;
}

function emptyValue(field: SchemaField): { omit: true } | { omit: false; value: null } | { error: string } {
    if (field.required) return { error: "Required" };
    if (field.nullable) return { omit: false, value: null };
    return { omit: true };
}

type Converted = { ok: true; value: unknown } | { ok: true; omit: true } | { ok: false; error: string };

function convert(field: SchemaField, raw: FormValue | undefined): Converted {
    if (field.kind === "boolean") return { ok: true, value: raw === true };

    if (field.kind === "enum_array") {
        const selected = Array.isArray(raw) ? raw : [];
        if (field.minItems !== undefined && selected.length < field.minItems) {
            return { ok: false, error: `Choose at least ${field.minItems}` };
        }
        return { ok: true, value: selected };
    }

    const text = typeof raw === "string" ? raw.trim() : "";
    if (text === "") {
        const empty = emptyValue(field);
        if ("error" in empty) return { ok: false, error: empty.error };
        return empty.omit ? { ok: true, omit: true } : { ok: true, value: null };
    }

    switch (field.kind) {
        case "string":
            if (field.minLength !== undefined && text.length < field.minLength) {
                return { ok: false, error: `Must be at least ${field.minLength} characters` };
            }
            if (field.maxLength !== undefined && text.length > field.maxLength) {
                return { ok: false, error: `Must be at most ${field.maxLength} characters` };
            }
            return { ok: true, value: text };
        case "integer": {
            const n = parseInteger(text);
            if (n === null) return { ok: false, error: "Enter a whole number" };
            const rangeError = checkRange(field, n);
            return rangeError ? { ok: false, error: rangeError } : { ok: true, value: n };
        }
        case "number": {
            const n = Number(text);
            if (!Number.isFinite(n)) return { ok: false, error: "Enter a number" };
            const rangeError = checkRange(field, n);
            return rangeError ? { ok: false, error: rangeError } : { ok: true, value: n };
        }
        case "enum": {
            const option = field.options?.find((o) => String(o) === text);
            return option === undefined
                ? { ok: false, error: "Choose one of the options" }
                : { ok: true, value: option };
        }
        case "string_array":
        case "integer_array": {
            const parts = text.split(",").map((p) => p.trim()).filter(Boolean);
            if (field.minItems !== undefined && parts.length < field.minItems) {
                return { ok: false, error: `Enter at least ${field.minItems}` };
            }
            if (field.kind === "string_array") return { ok: true, value: parts };
            const numbers: number[] = [];
            for (const part of parts) {
                const n = parseInteger(part);
                if (n === null) return { ok: false, error: "Enter whole numbers separated by commas" };
                const rangeError = checkRange(field, n);
                if (rangeError) return { ok: false, error: `${part}: ${rangeError.toLowerCase()}` };
                numbers.push(n);
            }
            return { ok: true, value: numbers };
        }
    }
    return { ok: false, error: "Unsupported field" };
}

/**
 * Validates the form and builds the config to send. Empty optional fields are
 * left out (the server keeps its default), or sent as null when nullable.
 */
export function valuesToConfig(
    fields: SchemaField[],
    values: FormValues,
): { config: Record<string, unknown>; errors: FormErrors } {
    const config: Record<string, unknown> = {};
    const errors: FormErrors = {};
    for (const field of fields) {
        const result = convert(field, values[field.key]);
        if (!result.ok) {
            errors[field.key] = result.error;
        } else if (!("omit" in result)) {
            config[field.key] = result.value;
        }
    }
    return { config, errors };
}
