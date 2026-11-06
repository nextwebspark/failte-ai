import type {
    IntegrationConnectionResponse,
    TemplateSetupField,
    WorkflowTemplateResponse,
} from '@/client/types.gen';

/** The integration providers the Create agent wizard can connect. */
export const GOOGLE_CALENDAR = 'google-calendar';

export const INTEGRATION_LABEL: Record<string, string> = {
    [GOOGLE_CALENDAR]: 'Google Calendar',
};

/** OAuth clients are saved per auth family: Google Calendar signs in with Google's. */
export const INTEGRATION_AUTH_FAMILY: Record<string, string> = {
    [GOOGLE_CALENDAR]: 'google',
};

export type TemplateDirectionFilter = 'all' | 'inbound' | 'outbound';

/** @deprecated Prefer TemplateDirectionFilter; kept for older imports. */
export type TemplateFilter = TemplateDirectionFilter;

export const TEMPLATE_FILTER_LABEL: Record<TemplateDirectionFilter, string> = {
    all: 'All',
    inbound: 'Answer my calls',
    outbound: 'Call my customers',
};

export type TemplateCategory =
    | 'all'
    | 'general'
    | 'telephony'
    | 'clinic'
    | 'trades'
    | 'restaurant'
    | 'estate'
    | 'salon';

export const TEMPLATE_CATEGORY_LABEL: Record<Exclude<TemplateCategory, 'all'>, string> = {
    general: 'General',
    telephony: 'Phone & VoIP',
    clinic: 'Clinics',
    trades: 'Trades',
    restaurant: 'Restaurants',
    estate: 'Estate agents',
    salon: 'Salons',
};

/** Featured templates first, then by name. */
export function sortTemplates(templates: WorkflowTemplateResponse[]): WorkflowTemplateResponse[] {
    return [...templates].sort(
        (a, b) =>
            Number(b.featured ?? false) - Number(a.featured ?? false) ||
            a.template_name.localeCompare(b.template_name),
    );
}

/** The direction filters worth showing: only when the templates span both directions. */
export function templateFilters(templates: WorkflowTemplateResponse[]): TemplateDirectionFilter[] {
    const types = new Set(templates.map((t) => t.call_type).filter(Boolean));
    return types.has('inbound') && types.has('outbound') ? ['all', 'inbound', 'outbound'] : [];
}

/** Category chips when more than one category is present. */
export function templateCategories(templates: WorkflowTemplateResponse[]): TemplateCategory[] {
    const cats = new Set(
        templates.map((t) => t.category).filter((c): c is string => Boolean(c && c.trim())),
    );
    if (cats.size <= 1) return [];
    const known = (Object.keys(TEMPLATE_CATEGORY_LABEL) as Exclude<TemplateCategory, 'all'>[]).filter(
        (c) => cats.has(c),
    );
    const extra = [...cats].filter((c) => !(c in TEMPLATE_CATEGORY_LABEL)).sort();
    return ['all', ...known, ...(extra as TemplateCategory[])];
}

export function filterTemplates(
    templates: WorkflowTemplateResponse[],
    direction: TemplateDirectionFilter,
    category: TemplateCategory = 'all',
): WorkflowTemplateResponse[] {
    return templates.filter((t) => {
        if (direction !== 'all' && t.call_type !== direction) return false;
        if (category !== 'all' && (t.category || 'general') !== category) return false;
        return true;
    });
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

/** The answers a template's questions start with: empty, and toggles at their defaults. */
export function emptyAnswers(fields: TemplateSetupField[]): Record<string, string> {
    return Object.fromEntries(
        fields.map((field) => [
            field.key,
            field.type === 'toggles'
                ? (field.options ?? []).filter((option) => option.default).map((option) => option.value).join(',')
                : '',
        ]),
    );
}

/** The chosen values of a toggles answer ("party_size,allergies"). */
export function chosenToggles(answer: string): Set<string> {
    return new Set(answer.split(',').map((part) => part.trim()).filter(Boolean));
}

/** Turn one toggle on or off; the answer keeps the options' order. */
export function withToggle(field: TemplateSetupField, answer: string, value: string, on: boolean): string {
    const chosen = chosenToggles(answer);
    if (on) chosen.add(value);
    else chosen.delete(value);
    return (field.options ?? [])
        .map((option) => option.value)
        .filter((v) => chosen.has(v))
        .join(',');
}

/** The first required question still unanswered, or null when all are. */
export function missingAnswer(
    fields: TemplateSetupField[],
    answers: Record<string, string>,
): TemplateSetupField | null {
    return (
        fields.find(
            (field) => field.type !== 'toggles' && (field.required ?? true) && !answers[field.key]?.trim(),
        ) ?? null
    );
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

/** Conversation steps from the template graph (start + agent nodes), for the preview. */
export function templateFlowSteps(template: WorkflowTemplateResponse): string[] {
    const nodes = (
        template.template_json as {
            nodes?: { type?: string; data?: { name?: unknown; is_start?: boolean } }[];
        }
    ).nodes;
    if (!nodes?.length) return [];
    const steps: string[] = [];
    for (const node of nodes) {
        if (node.type !== 'startCall' && node.type !== 'agentNode') continue;
        const name = typeof node.data?.name === 'string' ? node.data.name.trim() : '';
        if (name) steps.push(name);
    }
    return steps;
}

/** Short capability bullets for the gallery preview pane. */
export function templateHighlights(template: WorkflowTemplateResponse): string[] {
    const highlights: string[] = [];
    if (template.call_type === 'outbound') {
        highlights.push('Calls your customers on a VoIP or phone line');
        highlights.push('Introduces your business and follows a clear script');
    } else {
        highlights.push('Answers inbound calls on your VoIP or phone number');
        highlights.push('Uses your business details for hours, location and FAQs');
    }
    if (template.integrations?.includes(GOOGLE_CALENDAR)) {
        highlights.push('Can book into Google Calendar (optional)');
    } else {
        highlights.push('Takes a message when it cannot finish the request');
    }
    const fields = template.setup_fields?.length ?? 0;
    if (fields > 0) {
        highlights.push(`About ${setupMinutes(template)} minutes to personalise`);
    }
    return highlights;
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

/** The connection the wizard can attach for *provider*: active and installed as a tool. */
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
