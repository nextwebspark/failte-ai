import { describe, expect, it } from 'vitest';

import type { IntegrationConnectionResponse, WorkflowTemplateResponse } from '@/client/types.gen';

import {
    agentNameFor,
    filterTemplates,
    missingAnswer,
    previewParts,
    sortTemplates,
    templateFilters,
    templateGreeting,
    templateMeta,
    usableConnection,
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

    it('describes a card in plain words', () => {
        expect(templateMeta(template({ integrations: ['google-calendar'] }))).toBe(
            'Answers calls · Calendar · 2 min',
        );
        expect(templateMeta(template({ call_type: 'outbound', setup_fields: [] }))).toBe('Makes calls · 1 min');
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
