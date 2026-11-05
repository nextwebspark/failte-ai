import { describe, expect, it } from 'vitest';

import type { IntegrationConnectionResponse, WorkflowTemplateResponse } from '@/client/types.gen';

import {
    agentNameFor,
    chosenToggles,
    emptyAnswers,
    filterTemplates,
    missingAnswer,
    previewParts,
    sortTemplates,
    templateCategories,
    templateFilters,
    templateFlowSteps,
    templateGreeting,
    templateHighlights,
    templateMeta,
    usableConnection,
    withToggle,
} from './agentTemplates';

const FIELDS = [
    { key: 'business_name', label: 'Business name' },
    { key: 'address', label: 'Address', required: false },
];

function template(overrides: Partial<WorkflowTemplateResponse> = {}): WorkflowTemplateResponse {
    return {
        id: 1,
        template_name: 'AI Receptionist',
        template_description: 'Answers calls',
        template_json: {
            nodes: [
                { type: 'globalNode', data: {} },
                { type: 'startCall', data: { greeting: 'Hi, thanks for calling {{ business_name }}.' } },
            ],
        },
        setup_fields: FIELDS,
        call_type: 'inbound',
        integrations: [],
        created_at: '',
        ...overrides,
    };
}

describe('the gallery', () => {
    it('puts featured templates first, then sorts by name', () => {
        const sorted = sortTemplates([
            template({ id: 1, template_name: 'Bravo' }),
            template({ id: 2, template_name: 'Alpha' }),
            template({ id: 3, template_name: 'Zulu', featured: true }),
        ]);
        expect(sorted.map((t) => t.id)).toEqual([3, 2, 1]);
    });

    it('offers filters only when templates both answer and make calls', () => {
        const inbound = template({ id: 1 });
        const outbound = template({ id: 2, call_type: 'outbound' });
        expect(templateFilters([inbound])).toEqual([]);
        expect(templateFilters([inbound, outbound])).toEqual(['all', 'inbound', 'outbound']);
        expect(filterTemplates([inbound, outbound], 'outbound')).toEqual([outbound]);
    });

    it('offers category chips when more than one industry is present', () => {
        const clinic = template({ id: 1, category: 'clinic' });
        const trades = template({ id: 2, category: 'trades' });
        expect(templateCategories([clinic])).toEqual([]);
        expect(templateCategories([clinic, trades])).toEqual(['all', 'clinic', 'trades']);
        expect(filterTemplates([clinic, trades], 'all', 'clinic')).toEqual([clinic]);
    });

    it('describes a card in plain words', () => {
        expect(templateMeta(template({ integrations: ['google-calendar'] }))).toBe(
            'Answers calls · Calendar · 2 min',
        );
        expect(templateMeta(template({ call_type: 'outbound', setup_fields: [] }))).toBe('Makes calls · 1 min');
    });

    it('lists preview highlights and flow steps', () => {
        const withCal = template({
            integrations: ['google-calendar'],
            template_json: {
                nodes: [
                    { type: 'startCall', data: { name: 'start call', greeting: 'Hi' } },
                    { type: 'agentNode', data: { name: 'Take a message' } },
                ],
            },
        });
        expect(templateHighlights(withCal).some((h) => /calendar/i.test(h))).toBe(true);
        expect(templateFlowSteps(withCal)).toEqual(['start call', 'Take a message']);
    });

    it('lists unknown categories after the known ones, and treats a missing one as general', () => {
        const spa = template({ id: 1, category: 'spa' });
        const salon = template({ id: 2, category: 'salon' });
        const clinic = template({ id: 3, category: 'clinic' });
        const uncategorised = template({ id: 4, category: null });
        expect(templateCategories([spa, salon, clinic, uncategorised])).toEqual(['all', 'clinic', 'salon', 'spa']);
        expect(filterTemplates([salon, uncategorised], 'all', 'general')).toEqual([uncategorised]);
    });

    it('combines the direction and industry filters', () => {
        const inboundClinic = template({ id: 1, category: 'clinic' });
        const outboundClinic = template({ id: 2, category: 'clinic', call_type: 'outbound' });
        const outboundTrades = template({ id: 3, category: 'trades', call_type: 'outbound' });
        const all = [inboundClinic, outboundClinic, outboundTrades];
        expect(filterTemplates(all, 'outbound', 'clinic')).toEqual([outboundClinic]);
        expect(filterTemplates(all, 'inbound', 'trades')).toEqual([]);
    });

    it('describes outbound agents and agents without a calendar honestly', () => {
        const outbound = template({ call_type: 'outbound', integrations: [], setup_fields: [] });
        const highlights = templateHighlights(outbound);
        expect(highlights[0]).toMatch(/Calls your customers/);
        expect(highlights.some((h) => /calendar/i.test(h))).toBe(false);
        expect(highlights).toContain('Takes a message when it cannot finish the request');
        // No questions, so no setup time is promised.
        expect(highlights.some((h) => /minutes to personalise/.test(h))).toBe(false);
    });

    it('has no flow steps for a template without a graph', () => {
        expect(templateFlowSteps(template({ template_json: {} }))).toEqual([]);
    });
});

describe('setting a template up', () => {
    it('finds the first unanswered required question', () => {
        expect(missingAnswer(FIELDS, { business_name: '  ', address: '' })?.key).toBe('business_name');
        expect(missingAnswer(FIELDS, { business_name: 'Bloom', address: '' })).toBeNull();
    });

    it('names the agent after the business', () => {
        expect(agentNameFor(template(), { business_name: ' Bloom Dental ' })).toBe('AI Receptionist · Bloom Dental');
        expect(agentNameFor(template(), {})).toBe('AI Receptionist');
    });

    it('previews the greeting with the answers filled in', () => {
        const greeting = templateGreeting(template());
        expect(greeting).toBe('Hi, thanks for calling {{ business_name }}.');
        expect(previewParts(greeting!, FIELDS, { business_name: 'Bloom Dental' })).toEqual([
            { text: 'Hi, thanks for calling ', answer: false },
            { text: 'Bloom Dental', answer: true },
            { text: '.', answer: false },
        ]);
        expect(previewParts(greeting!, FIELDS, {})[1]).toEqual({ text: '[Business name]', answer: true });
    });

    it('uses a placeholder’s fallback and leaves other variables alone', () => {
        const text = 'At {{address | fallback:our clinic}} for {{first_name}}';
        expect(previewParts(text, FIELDS, {}).map((p) => p.text)).toEqual([
            'At ',
            'our clinic',
            ' for {{first_name}}',
        ]);
    });

    it('only counts an active, installed connection as connected', () => {
        const base = { auth_mode: 'oauth2', created_at: '', updated_at: '' };
        const connections = [
            { ...base, id: 'a', provider: 'google-calendar', status: 'error', tool_uuids: ['t1'] },
            { ...base, id: 'b', provider: 'google-calendar', status: 'active', tool_uuids: [] },
            { ...base, id: 'c', provider: 'google-calendar', status: 'active', tool_uuids: ['t3'] },
        ] as IntegrationConnectionResponse[];
        expect(usableConnection(connections, 'google-calendar')?.id).toBe('c');
        expect(usableConnection(connections.slice(0, 2), 'google-calendar')).toBeNull();
    });
});

describe('booking toggles', () => {
    const field = {
        key: 'booking_questions',
        label: 'When someone books, also ask',
        type: 'toggles' as const,
        required: false,
        options: [
            { value: 'party_size', label: 'Party size', prompt: 'how many people', default: true },
            { value: 'allergies', label: 'Allergies', prompt: 'about allergies', default: true },
            { value: 'occasion', label: 'Special occasion', prompt: 'about an occasion' },
        ],
    };

    it('start at their defaults, and are never "missing"', () => {
        expect(emptyAnswers([field])).toEqual({ booking_questions: 'party_size,allergies' });
        expect(missingAnswer([field], { booking_questions: '' })).toBeNull();
    });

    it('keep the options order whatever the click order', () => {
        expect(withToggle(field, 'allergies', 'party_size', true)).toBe('party_size,allergies');
        expect(withToggle(field, 'party_size,allergies', 'party_size', false)).toBe('allergies');
        expect(withToggle(field, '', 'occasion', true)).toBe('occasion');
        expect([...chosenToggles(' party_size , occasion ')]).toEqual(['party_size', 'occasion']);
    });
});
