'use client';

import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { client } from '@/client/client.gen';
import { getCurrentOrganizationContextApiV1OrganizationsContextGet, getPreferencesApiV1OrganizationsPreferencesGet, getUserConfigurationsApiV1UserConfigurationsUserGet } from '@/client/sdk.gen';
import type { OrganizationContextResponse, OrganizationPreferencesResponse, UserConfigurationRequestResponseSchema } from '@/client/types.gen';
import { setupAuthInterceptor } from '@/lib/apiClient';
import { detailFromError } from '@/lib/apiError';
import type { AuthUser } from '@/lib/auth';
import { useAuth } from '@/lib/auth';
import type { OrgRole, Permission } from '@/lib/auth/roles';

interface OrganizationPricing {
    price_per_second_usd: number | null;
    currency: string;
    billing_enabled: boolean;
}

interface OrgConfigContextType {
    orgContext: OrganizationContextResponse | null;
    userConfig: UserConfigurationRequestResponseSchema | null;
    loading: boolean;
    error: Error | null;
    refreshConfig: () => Promise<void>;
    /** The caller's role in the selected organization (null until loaded). */
    role: OrgRole | null;
    permissions: readonly Permission[];
    /** True when the caller's role grants every given permission. Always
     *  false until the organization context has loaded. */
    can: (...required: Permission[]) => boolean;
    user: AuthUser | null;
    organizationPricing: OrganizationPricing | null;
    organizationPreferences: OrganizationPreferencesResponse | null;
    externalPbxIntegrationsEnabled: boolean;
}

const OrgConfigContext = createContext<OrgConfigContextType | null>(null);

const pricingFromUserConfig = (
    userConfig: UserConfigurationRequestResponseSchema,
): OrganizationPricing | null => {
    if (!userConfig.organization_pricing) {
        return null;
    }

    return {
        price_per_second_usd: userConfig.organization_pricing.price_per_second_usd as number | null,
        currency: (userConfig.organization_pricing.currency as string) || 'USD',
        billing_enabled: (userConfig.organization_pricing.billing_enabled as boolean) || false,
    };
};

export function OrgConfigProvider({ children }: { children: ReactNode }) {
    const [orgContext, setOrgContext] = useState<OrganizationContextResponse | null>(null);
    const [userConfig, setUserConfig] = useState<UserConfigurationRequestResponseSchema | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);
    const [organizationPricing, setOrganizationPricing] = useState<OrganizationPricing | null>(null);
    const [organizationPreferences, setOrganizationPreferences] = useState<OrganizationPreferencesResponse | null>(null);

    const auth = useAuth();

    const authRef = useRef(auth);
    authRef.current = auth;

    const hasFetchedConfig = useRef(false);

    if (!auth.loading && auth.isAuthenticated) {
        setupAuthInterceptor(client, auth.getAccessToken);
    }

    const fetchConfig = useCallback(async () => {
        const currentAuth = authRef.current;
        if (!currentAuth.isAuthenticated) {
            return;
        }

        setLoading(true);
        try {
            const [orgContextResponse, userConfigResponse, preferencesResponse] = await Promise.all([
                getCurrentOrganizationContextApiV1OrganizationsContextGet(),
                getUserConfigurationsApiV1UserConfigurationsUserGet(),
                getPreferencesApiV1OrganizationsPreferencesGet(),
            ]);

            if (preferencesResponse.error) {
                throw new Error(detailFromError(preferencesResponse.error, 'Failed to load organization preferences'));
            }

            if (orgContextResponse.data) {
                setOrgContext(orgContextResponse.data);
            }

            if (userConfigResponse.data) {
                setUserConfig(userConfigResponse.data);
                setOrganizationPricing(pricingFromUserConfig(userConfigResponse.data));
            }

            if (preferencesResponse.data) {
                setOrganizationPreferences(preferencesResponse.data);
            }

            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err : new Error('Failed to fetch organization configuration'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (auth.loading || !auth.isAuthenticated || hasFetchedConfig.current) {
            return;
        }
        hasFetchedConfig.current = true;
        fetchConfig();
    }, [auth.loading, auth.isAuthenticated, fetchConfig]);

    const refreshConfig = useCallback(async () => {
        await fetchConfig();
    }, [fetchConfig]);

    const permissions = useMemo<readonly Permission[]>(
        () => orgContext?.permissions ?? [],
        [orgContext],
    );
    const can = useCallback(
        (...required: Permission[]) => required.every((p) => permissions.includes(p)),
        [permissions],
    );

    return (
        <OrgConfigContext.Provider
            value={{
                orgContext,
                userConfig,
                loading,
                error,
                refreshConfig,
                role: orgContext?.role ?? null,
                permissions,
                can,
                user: auth.user,
                organizationPricing,
                organizationPreferences,
                externalPbxIntegrationsEnabled:
                    organizationPreferences?.external_pbx_integrations_enabled ?? false,
            }}
        >
            {children}
        </OrgConfigContext.Provider>
    );
}

export function useOrgConfig() {
    const context = useContext(OrgConfigContext);
    if (!context) {
        throw new Error('useOrgConfig must be used within an OrgConfigProvider');
    }
    return context;
}
