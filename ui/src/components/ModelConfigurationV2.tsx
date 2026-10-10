"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get,
    getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet,
    saveModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Put,
} from "@/client/sdk.gen";
import type {
    ModelConfigurationPricingResponse,
    ModelConfigurationV2Defaults,
    OrganizationAiModelConfigurationResponse,
    OrganizationAiModelConfigurationV2,
} from "@/client/types.gen";
import {
    AIModelConfigurationV2Editor,
    legacyModelConfigurationDefaults,
} from "@/components/AIModelConfigurationV2Editor";
import { PlatformModelEditor } from "@/components/platform/PlatformModelEditor";
import { Skeleton } from "@/components/ui/skeleton";
import { useAppConfig } from "@/context/AppConfigContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useUserConfig } from "@/context/UserConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { fetchModelConfigurationPricing } from "@/lib/modelConfigurationPricing";

export default function ModelConfigurationV2() {
    const auth = useAuth();
    const { refreshConfig } = useUserConfig();
    const { config: appConfig } = useAppConfig();
    const { can } = useOrgConfig();
    const hasFetched = useRef(false);

    const [defaults, setDefaults] = useState<ModelConfigurationV2Defaults | null>(null);
    const [response, setResponse] = useState<OrganizationAiModelConfigurationResponse | null>(null);
    const [pricing, setPricing] = useState<ModelConfigurationPricingResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    useEffect(() => {
        if (auth.loading || !auth.user || hasFetched.current) return;
        hasFetched.current = true;

        const load = async () => {
            setLoading(true);
            setError(null);
            const [defaultsResult, configResult, pricingResult] = await Promise.all([
                getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet(),
                getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get(),
                fetchModelConfigurationPricing(),
            ]);

            if (defaultsResult.error) {
                setError(detailFromError(defaultsResult.error, "Failed to load model configuration defaults"));
                setLoading(false);
                return;
            }
            if (configResult.error) {
                setError(detailFromError(configResult.error, "Failed to load model configuration"));
                setLoading(false);
                return;
            }

            const nextDefaults = defaultsResult.data;
            if (!nextDefaults || !configResult.data) {
                setError("Failed to load model configuration");
                setLoading(false);
                return;
            }
            setDefaults(nextDefaults);
            setResponse(configResult.data);
            setPricing(pricingResult);
            setLoading(false);
        };

        load();

    }, [auth.loading, auth.user]);

    // The catalog reports whether this server runs platform models; the app
    // flag covers the moment before it loads.
    const platformModels = defaults?.platform.enabled ?? Boolean(appConfig?.platformModelsEnabled);
    const legacyDefaults = legacyModelConfigurationDefaults(defaults ?? undefined);

    const saveConfiguration = async (configuration: OrganizationAiModelConfigurationV2) => {
        if (!defaults) return;
        setError(null);
        setNotice(null);

        const result = await saveModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Put({
            body: configuration,
        });

        if (result.error) {
            throw new Error(detailFromError(result.error, "Failed to save model configuration"));
        }
        if (!result.data) {
            throw new Error("Failed to save model configuration");
        }

        setResponse(result.data);
        void fetchModelConfigurationPricing().then(setPricing);
        await refreshConfig();
        if (platformModels) {
            toast.success("Model settings saved");
        } else {
            setNotice("Model configuration saved");
        }
    };

    if (loading) {
        return (
            <div className="w-full max-w-4xl mx-auto space-y-6">
                <Skeleton className="h-10 w-80" />
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-96 w-full" />
            </div>
        );
    }

    return (
        <div className="w-full max-w-4xl mx-auto space-y-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                    <h1 className="text-3xl font-bold">
                        {platformModels ? "Models & voice" : "AI Models Configuration"}
                    </h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        {platformModels
                            ? "Choose how your agents listen, think and speak. Everything runs on Fallcha's managed models in the EU, no API keys needed."
                            : "Organization-scoped model settings."}
                    </p>
                </div>
            </div>

            {error && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                </div>
            )}
            {notice && (
                <div className="rounded-md border border-green-500/40 bg-green-500/10 px-4 py-3 text-sm text-green-700 dark:text-green-300">
                    {notice}
                </div>
            )}

            {defaults && response && platformModels && (
                <PlatformModelEditor
                    catalog={defaults.platform}
                    configuration={response.configuration}
                    onSave={saveConfiguration}
                    readOnly={!can("credentials:write")}
                />
            )}
            {legacyDefaults && response && !platformModels && (
                <AIModelConfigurationV2Editor
                    defaults={legacyDefaults}
                    configuration={response.configuration}
                    effectiveConfiguration={response.effective_configuration}
                    pricing={pricing}
                    onSave={saveConfiguration}
                />
            )}
        </div>
    );
}
