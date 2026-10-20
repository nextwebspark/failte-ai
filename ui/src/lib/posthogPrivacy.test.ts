import type { CaptureResult } from 'posthog-js';
import { describe, expect, it } from 'vitest';

import { posthogPrivacyOptions, stripQuery, stripUrlQueries } from './posthogPrivacy';

describe('stripQuery', () => {
    it('drops the query string and fragment', () => {
        expect(stripQuery('https://app.example.com/invite?email=a%40b.com#x')).toBe(
            'https://app.example.com/invite',
        );
        expect(stripQuery('https://app.example.com/a#token=1')).toBe('https://app.example.com/a');
        expect(stripQuery('https://app.example.com/a')).toBe('https://app.example.com/a');
    });
});

describe('stripUrlQueries', () => {
    it('strips URL properties in the event and person properties', () => {
        const event = {
            uuid: '1',
            event: '$pageview',
            properties: {
                $current_url: 'https://app.example.com/calls?phone=%2B353871234567',
                $referrer: 'https://google.com/search?q=me',
                $pathname: '/calls',
                title: 'keep?this',
            },
            $set_once: { $initial_current_url: 'https://app.example.com/?code=abc' },
        } as CaptureResult;

        const result = stripUrlQueries(event)!;

        expect(result.properties).toEqual({
            $current_url: 'https://app.example.com/calls',
            $referrer: 'https://google.com/search',
            $pathname: '/calls',
            title: 'keep?this',
        });
        expect(result.$set_once).toEqual({ $initial_current_url: 'https://app.example.com/' });
    });

    it('passes a dropped event through', () => {
        expect(stripUrlQueries(null)).toBeNull();
    });
});

describe('posthogPrivacyOptions', () => {
    it('turns off autocapture, replay and exception capture', () => {
        expect(posthogPrivacyOptions).toMatchObject({
            autocapture: false,
            disable_session_recording: true,
            capture_exceptions: false,
            person_profiles: 'identified_only',
            persistence: 'memory',
        });
    });
});
