/**
 * Settings picked from a list the provider reads live (the `choices`
 * capability), e.g. which Calendly event callers book. The provider's config
 * schema marks the picked value's field and its display name's field with
 * `x-fallcha-choice: "value"` / `"label"`.
 */

import { CHOICE_MARK } from "./schemaForm";

export interface ChoiceKeys {
    value: string;
    label: string | null;
}

type Provider = { capabilities?: string[] | null; config_schema?: unknown } | null | undefined;
type Connection = { config?: Record<string, unknown> | null };

function properties(schema: unknown): Record<string, unknown> {
    const props = (schema as { properties?: unknown } | null | undefined)?.properties;
    return typeof props === "object" && props !== null ? (props as Record<string, unknown>) : {};
}

/** Which config fields hold the picked value and its name, or null if none. */
export function choiceKeys(schema: unknown): ChoiceKeys | null {
    let value: string | null = null;
    let label: string | null = null;
    for (const [key, raw] of Object.entries(properties(schema))) {
        const mark = (raw as Record<string, unknown> | null)?.[CHOICE_MARK];
        if (mark === "value") value = key;
        if (mark === "label") label = key;
    }
    return value ? { value, label } : null;
}

export function hasChoices(provider: Provider): boolean {
    return Boolean(provider?.capabilities?.includes("choices") && choiceKeys(provider.config_schema));
}

/** The name of what was picked, else its raw value; null when nothing is. */
export function chosenLabel(provider: Provider, connection: Connection): string | null {
    const keys = hasChoices(provider) ? choiceKeys(provider?.config_schema) : null;
    if (!keys) return null;
    const config = connection.config ?? {};
    const value = config[keys.value];
    if (typeof value !== "string" || !value) return null;
    const label = keys.label ? config[keys.label] : null;
    return typeof label === "string" && label.trim() ? label.trim() : value;
}

/** True when the provider needs something picked and nothing is yet. */
export function needsChoice(provider: Provider, connection: Connection): boolean {
    return hasChoices(provider) && chosenLabel(provider, connection) === null;
}
