import type {
    IntegrationConnectionResponse,
    TemplateSetupField,
    WorkflowTemplateResponse,
} from '@/client/types.gen';

/** The integration providers the Create agent dialog can connect. */
export const GOOGLE_CALENDAR = 'google-calendar';

export const INTEGRATION_LABEL: Record<string, string> = {
    [GOOGLE_CALENDAR]: 'Google Calendar',
};

/** OAuth clients are saved per auth family: Google Calendar signs in with Google's. */
export const INTEGRATION_AUTH_FAMILY: Record<string, string> = {
    [GOOGLE_CALENDAR]: 'google',
};

export type TemplateFilter = 'all' | 'inbound' | 'outbound';

export const TEMPLATE_FILTER_LABEL: Record<TemplateFilter, string> = {
    all: 'All',
    inbound: 'Answer my calls',
    outbound: 'Call my customers',
};

/** Featured templates first, then by name. */
export function sortTemplates(templates: WorkflowTemplateResponse[]): WorkflowTemplateResponse[] {
    return [...templates].sort(
        (a, b) =>
            Number(b.featured ?? false) - Number(a.featured ?? false) ||
            a.template_name.localeCompare(b.template_name),
    );
}

/** The filters worth showing: only when the templates span both directions. */
export function templateFilters(templates: WorkflowTemplateResponse[]): TemplateFilter[] {
    const types = new Set(templates.map((t) => t.call_type).filter(Boolean));
    return types.has('inbound') && types.has('outbound') ? ['all', 'inbound', 'outbound'] : [];
}

export function filterTemplates(
    templates: WorkflowTemplateResponse[],
    filter: TemplateFilter,
): WorkflowTemplateResponse[] {
    return filter === 'all' ? templates : templates.filter((t) => t.call_type === filter);
}

/** About a minute per two questions, plus one to try it. */
export function setupMinutes(template: WorkflowTemplateResponse): number {
    return 1 + Math.ceil((template.setup_fields?.length ?? 0) / 2);
}

/** "Answers calls · Calendar · 3 min" for a template card. */
export function templateMeta(template: WorkflowTemplateResponse): string {
    const parts: string[] = [];
    if (template.call_type === 'inbound') parts.push('Answers calls');
    if (template.call_type === 'outbound') parts.push('Makes calls');
    if (template.integrations?.includes(GOOGLE_CALENDAR)) parts.push('Calendar');
    parts.push(`${setupMinutes(template)} min`);
    return parts.join(' · ');
}

/** The answers a template's questions start with: all empty. */
export function emptyAnswers(fields: TemplateSetupField[]): Record<string, string> {
    return Object.fromEntries(fields.map((field) => [field.key, '']));
}

/** The first required question still unanswered, or null when all are. */
export function missingAnswer(
    fields: TemplateSetupField[],
    answers: Record<string, string>,
): TemplateSetupField | null {
    return fields.find((field) => (field.required ?? true) && !answers[field.key]?.trim()) ?? null;
}

/** "AI Receptionist · Bloom Dental", or just the template's name. */
export function agentNameFor(template: WorkflowTemplateResponse, answers: Record<string, string>): string {
    const business = answers.business_name?.trim();
    return (business ? `${template.template_name} · ${business}` : template.template_name).slice(0, 200);
}

/** The first thing a caller hears: the start step's greeting. */
export function templateGreeting(template: WorkflowTemplateResponse): string | null {
    const nodes = (template.template_json as { nodes?: { type?: string; data?: { greeting?: unknown } }[] })
        .nodes;
    const greeting = nodes?.find((node) => node.type === 'startCall')?.data?.greeting;
    return typeof greeting === 'string' && greeting.trim() ? greeting : null;
}

export interface PreviewPart {
    text: string;
    /** True for text that came from (or stands in for) an answer. */
    answer: boolean;
}

const PLACEHOLDER = /\{\{\s*([a-z][a-z0-9_]*)\s*(?:\|\s*(?:fallback\s*:)?\s*([^}]*?))?\s*\}\}/g;

/**
 * Splits *text* into plain parts and answer parts, filling each setup
 * question's placeholder the way the server will: the answer, else the
 * placeholder's fallback. An unanswered question shows its label in brackets.
 */
export function previewParts(
    text: string,
    fields: TemplateSetupField[],
    answers: Record<string, string>,
): PreviewPart[] {
    const byKey = new Map(fields.map((field) => [field.key, field]));
    const parts: PreviewPart[] = [];
    let last = 0;
    for (const match of text.matchAll(PLACEHOLDER)) {
        const field = byKey.get(match[1]);
        if (!field) continue;
        const index = match.index ?? 0;
        if (index > last) parts.push({ text: text.slice(last, index), answer: false });
        const answer = answers[field.key]?.trim();
        parts.push({ text: answer || match[2]?.trim() || `[${field.label}]`, answer: true });
        last = index + match[0].length;
    }
    if (last < text.length) parts.push({ text: text.slice(last), answer: false });
    return parts;
}

/** The connection the dialog can attach for *provider*: active and installed as a tool. */
export function usableConnection(
    connections: IntegrationConnectionResponse[],
    provider: string,
): IntegrationConnectionResponse | null {
    return (
        connections.find(
            (c) => c.provider === provider && c.status === 'active' && (c.tool_uuids?.length ?? 0) > 0,
        ) ?? null
    );
}
