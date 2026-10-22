'use client';

import posthog from 'posthog-js';
import { useEffect } from 'react';

import { PostHogEvent } from '@/constants/posthog-events';
import { useAuth } from '@/lib/auth';

/**
 * PostHogIdentify
 * ---------------
 * Calls `posthog.identify` once the authenticated user object is available,
 * using the provider ID as distinct_id. No email or name is sent.
 *
 * Rendered in the root layout (`app/layout.tsx`) so it fires on every session
 * for every logged-in user.
 */
export default function PostHogIdentify() {
    const { user } = useAuth();

    useEffect(() => {
        if (user) {
            const identify = () => {
                try {
                    // Use provider_id as distinct_id to match backend PostHog events.
                    // Stack Auth users: user.id is already the provider_id.
                    // OSS users: provider_id is returned from the auth API.
                    const distinctId =
                        'provider_id' in user && user.provider_id
                            ? String(user.provider_id)
                            : String(user.id);

                    // ID only: no email or name leaves for analytics.
                    posthog.identify(distinctId);
                    posthog.capture(PostHogEvent.SIGNED_IN);
                } catch (err) {
                    console.warn('Failed to identify user in PostHog', err);
                }
            };

            if (posthog.__loaded) {
                identify();
            } else {
                // PostHog initializes async — retry until ready
                let attempts = 0;
                const interval = setInterval(() => {
                    attempts++;
                    if (posthog.__loaded) {
                        identify();
                        clearInterval(interval);
                    } else if (attempts >= 20) {
                        clearInterval(interval);
                    }
                }, 200);
                return () => clearInterval(interval);
            }
        } else {
            posthog.reset();
        }
    }, [user]);

    return null;
}
