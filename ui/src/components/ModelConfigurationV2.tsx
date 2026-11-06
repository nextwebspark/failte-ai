"use client";

import { RotateCcw } from "lucide-react";
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
import { CurrentSetupCard } from "@/components/platform/CurrentSetupCard";
import { PlatformModelEditor } from "@/components/platform/PlatformModelEditor";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { BRAND } from "@/config/brand";
import { useAppConfig } from "@/context/AppConfigContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useUserConfig } from "@/context/UserConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { fetchModelConfigurationPricing } from "@/lib/modelConfigurationPricing";
import { isLegacyConfiguration, isPlatformConfiguration } from "@/lib/platformModelConfig";

export default function ModelConfigurationV2() {
    const auth = useAuth();
    const { refreshConfig } = useUserConfig();
    const { config: appConfig } = useAppConfig();
    const { can } = useOrgConfig();
    const hasFetched = useRef(false);
    // Bumped by "Try again" to load everything afresh.
    const [attempt, setAttempt] = useState(0);

    const [defaults, setDefaults] = useState<ModelConfigurationV2Defaults | null>(null);
    const [response, setResponse] = useState<OrganizationAiModelConfigurationResponse | null>(null);
    const [pricing, setPricing] = useState<ModelConfigurationPricingResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [editorDirty, setEditorDirty] = useState(false);

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

    }, [auth.loading, auth.user, attempt]);

    const retry = () => {
        hasFetched.current = false;
        setAttempt((n) => n + 1);
    };

    // The catalog reports whether this server runs platform models; the app
    // flag covers the moment before it loads.
    const platformModels = defaults?.platform.enabled ?? Boolean(appConfig?.platformModelsEnabled);
    const legacyDefaults = legacyModelConfigurationDefaults(defaults ?? undefined);
    const missingLegacyDefaults = Boolean(defaults) && !platformModels && !legacyDefaults;

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

    const header = (
        <PageHeader
            className="mb-0"
            title="Models & voice"
            description={
                platformModels
                    ? `Choose how your agents listen, think and speak. Everything runs on ${BRAND.shortName}'s managed models in the EU, no API keys needed.`
                    : "Choose the speech and AI models your agents use."
            }
        />
    );

    if (loading) {
        return (
            <div className="w-full max-w-4xl space-y-6">
                {header}
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-96 w-full" />
            </div>
        );
    }

    return (
        <div className="w-full max-w-4xl space-y-6">
            {header}

            {(error || missingLegacyDefaults) && (
                <div
                    role="alert"
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger-dim px-4 py-3"
                >
                    <div className="min-w-0">
                        <p className="text-sm font-medium text-foreground">Your model settings couldn&apos;t be loaded.</p>
                        {/* The API's reason, kept small, for the person who has to fix it. */}
                        {error && <p className="mt-0.5 text-xs text-ink-3">{error}</p>}
                    </div>
                    <Button size="sm" variant="outline" onClick={retry}>
                        <RotateCcw aria-hidden />
                        Try again
                    </Button>
                </div>
            )}
            {notice && (
                <div className="rounded-md border border-ok/40 bg-ok-dim px-4 py-3 text-sm text-ok">
                    {notice}
                </div>
            )}

            {defaults && response && platformModels && (
                <>
                    <CurrentSetupCard
                        catalog={defaults.platform}
                        configuration={response.configuration}
                        source={isLegacyConfiguration(response.configuration) ? "legacy" : "workspace"}
                        // A form opened from an older or missing setup differs from what is
                        // stored before anyone edits it; only a platform setup can be edited.
                        dirty={editorDirty && isPlatformConfiguration(response.configuration) && can("credentials:write")}
                        note="Agents without their own voice and model use this on every call."
                    />
                    <PlatformModelEditor
                        catalog={defaults.platform}
                        configuration={response.configuration}
                        onSave={saveConfiguration}
                        readOnly={!can("credentials:write")}
                        onDirtyChange={setEditorDirty}
                    />
                </>
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
