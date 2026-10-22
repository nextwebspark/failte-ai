import type { CaptureResult, PostHogConfig } from 'posthog-js';

// URL properties keep only origin + path: query strings and fragments can carry
// tokens, emails or phone numbers (e.g. invite links, OAuth callbacks).
const isUrlProperty = (key: string) => key.endsWith('_url') || key.endsWith('referrer');

export const stripQuery = (value: string): string => {
    const cut = value.search(/[?#]/);
    return cut === -1 ? value : value.slice(0, cut);
};

const sanitize = (properties?: Record<string, unknown>) => {
    if (!properties) return;
    for (const [key, value] of Object.entries(properties)) {
        if (typeof value === 'string' && isUrlProperty(key)) {
            properties[key] = stripQuery(value);
        }
    }
};

export const stripUrlQueries = (event: CaptureResult | null): CaptureResult | null => {
    if (!event) return event;
    sanitize(event.properties);
    sanitize(event.$set);
    sanitize(event.$set_once);
    return event;
};

// Shared by every posthog.init call: pageviews only, no autocaptured clicks or
// text, no session replay, no exception events (their messages and stack
// traces can contain personal data; Sentry handles errors), and no person
// profiles for anonymous visitors.
export const posthogPrivacyOptions: Partial<PostHogConfig> = {
    autocapture: false,
    disable_session_recording: true,
    capture_exceptions: false,
    person_profiles: 'identified_only',
    // Cookieless: no cookie or localStorage, so no consent banner needed.
    persistence: 'memory',
    before_send: stripUrlQueries,
};
