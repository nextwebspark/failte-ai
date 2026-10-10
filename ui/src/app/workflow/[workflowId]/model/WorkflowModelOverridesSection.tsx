"use client";

import { Brain, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get,
    getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet,
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
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useUnsavedChanges } from "@/context/UnsavedChangesContext";
import { detailFromError } from "@/lib/apiError";
import { fetchModelConfigurationPricing } from "@/lib/modelConfigurationPricing";
import {
    describePlatformConfiguration,
    isLegacyConfiguration,
    platformOverrideSeed,
} from "@/lib/platformModelConfig";
import type { WorkflowConfigurations } from "@/types/workflow-configurations";

const PUBLISH_WORKFLOW_REMINDER = "Test calls use it now; publish the agent to use it on phone calls.";

/**
 * The organization stack this agent may override. Loaded here rather than by
 * the page so the section stays self-contained.
 */
function useOrganizationModelConfiguration() {
    const [modelConfigurationDefaults, setModelConfigurationDefaults] = useState<ModelConfigurationV2Defaults | null>(null);
    const [organizationModelConfiguration, setOrganizationModelConfiguration] = useState<OrganizationAiModelConfigurationResponse | null>(null);
    const [modelConfigurationPricing, setModelConfigurationPricing] = useState<ModelConfigurationPricingResponse | null>(null);
    const [modelConfigurationLoading, setModelConfigurationLoading] = useState(true);
    const [modelConfigurationError, setModelConfigurationError] = useState<string | null>(null);
    const hasFetched = useRef(false);

    useEffect(() => {
        if (hasFetched.current) return;
        hasFetched.current = true;

        const load = async () => {
            setModelConfigurationLoading(true);
            setModelConfigurationError(null);
            const [defaultsResult, configurationResult, pricingResult] = await Promise.all([
                getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet(),
                getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get(),
                fetchModelConfigurationPricing(),
            ]);

            if (defaultsResult.error) {
                setModelConfigurationError(detailFromError(defaultsResult.error, "Failed to load model configuration defaults"));
                setModelConfigurationLoading(false);
                return;
            }
            if (configurationResult.error) {
                setModelConfigurationError(detailFromError(configurationResult.error, "Failed to load model configuration"));
                setModelConfigurationLoading(false);
                return;
            }

            if (!defaultsResult.data) {
                setModelConfigurationError("Failed to load model configuration defaults");
                setModelConfigurationLoading(false);
                return;
            }
            setModelConfigurationDefaults(defaultsResult.data);
            setOrganizationModelConfiguration(configurationResult.data || null);
            setModelConfigurationPricing(pricingResult);
            setModelConfigurationLoading(false);
        };

        void load();
    }, []);

    return {
        modelConfigurationDefaults,
        organizationModelConfiguration,
        modelConfigurationPricing,
        modelConfigurationLoading,
        modelConfigurationError,
    };
}

function withoutModelConfigurationOverrides(configurations: WorkflowConfigurations): WorkflowConfigurations {
    const next = { ...configurations };
    delete next.model_overrides;
    delete next.model_configuration_v2_override;
    return next;
}

export function WorkflowModelOverridesSection({
    workflowConfigurations,
    workflowName,
    onSave,
}: {
    workflowConfigurations: WorkflowConfigurations;
    workflowName: string;
    onSave: (configurations: WorkflowConfigurations, workflowName: string) => Promise<void>;
}) {
    const {
        modelConfigurationDefaults,
        organizationModelConfiguration,
        modelConfigurationPricing,
        modelConfigurationLoading,
        modelConfigurationError,
    } = useOrganizationModelConfiguration();
    const { can } = useOrgConfig();
    const savedV2Override = workflowConfigurations.model_configuration_v2_override;
    const hasSavedModelOverride = Boolean(savedV2Override || workflowConfigurations.model_overrides);
    const catalog = modelConfigurationDefaults?.platform;
    const platformModels = Boolean(catalog?.enabled);
    // On platform models only a platform override is one; an old provider
    // override is replaced by the workspace default on the next save.
    const hasActiveOverride = platformModels
        ? savedV2Override?.mode === "platform"
        : Boolean(savedV2Override);
    // An override from before platform models still runs until it is replaced.
    const hasLegacyOverride = platformModels
        && (isLegacyConfiguration(savedV2Override) || Boolean(workflowConfigurations.model_overrides));
    const [overrideEnabled, setOverrideEnabled] = useState(hasActiveOverride);
    const [isRemovingOverride, setIsRemovingOverride] = useState(false);
    const [editorDirty, setEditorDirty] = useState(false);
    useUnsavedChanges("model", overrideEnabled && editorDirty);

    useEffect(() => {
        setOverrideEnabled(hasActiveOverride);
    }, [hasActiveOverride, savedV2Override]);

    const hasOrgConfiguration = organizationModelConfiguration?.source === "organization_v2";
    const legacyDefaults = legacyModelConfigurationDefaults(modelConfigurationDefaults ?? undefined);
    const workspaceConfiguration = organizationModelConfiguration?.configuration ?? null;
    // Memoized: the editor resets whenever its configuration changes identity.
    const platformSeed = useMemo(
        () => platformOverrideSeed(savedV2Override, workspaceConfiguration),
        [savedV2Override, workspaceConfiguration],
    );

    const saveV2Override = async (configuration: OrganizationAiModelConfigurationV2) => {
        const nextConfigurations = withoutModelConfigurationOverrides(workflowConfigurations);
        nextConfigurations.model_configuration_v2_override = configuration;
        await onSave(nextConfigurations, workflowName);
        toast.success(
            `${platformModels ? "Agent voice & model saved." : "Model override saved."} ${PUBLISH_WORKFLOW_REMINDER}`,
        );
    };

    const removeV2Override = async () => {
        setIsRemovingOverride(true);
        try {
            await onSave(withoutModelConfigurationOverrides(workflowConfigurations), workflowName);
            setOverrideEnabled(false);
            toast.success(
                `${platformModels ? "This agent now uses the workspace default." : "Organization model configuration saved."} ${PUBLISH_WORKFLOW_REMINDER}`,
            );
        } finally {
            setIsRemovingOverride(false);
        }
    };

    return (
        <Card id="models">
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Brain className="h-4 w-4" />
                    Model and voice
                </CardTitle>
                <CardDescription>
                    {platformModels
                        ? "This agent uses the workspace voice and model unless you choose different ones here."
                        : "This agent speaks with the workspace LLM, speech and transcription stack unless you override the whole stack here."}
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                {modelConfigurationLoading && (
                    <div className="flex items-center gap-2 rounded-md border p-4 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading model configuration
                    </div>
                )}

                {modelConfigurationError && (
                    <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                        {modelConfigurationError}
                    </div>
                )}

                {!modelConfigurationLoading && !modelConfigurationError && platformModels && catalog && (
                    <>
                        <div className="flex items-center justify-between rounded-md border p-4">
                            <div className="space-y-0.5">
                                <Label htmlFor="workflow-model-v2-override" className="text-sm font-medium">
                                    Use a different voice or model for this agent
                                </Label>
                                <p id="workflow-model-v2-override-state" className="text-xs text-muted-foreground">
                                    {overrideEnabled
                                        ? "This agent uses its own voice and model."
                                        : hasLegacyOverride
                                          ? "This agent still uses an older provider setup."
                                          : "This agent uses the workspace voice and model."}
                                </p>
                            </div>
                            <Switch
                                id="workflow-model-v2-override"
                                aria-describedby="workflow-model-v2-override-state"
                                checked={overrideEnabled}
                                onCheckedChange={setOverrideEnabled}
                                // Pinned workspaces can still drop an override, never add one.
                                disabled={Boolean(catalog.locked) && !overrideEnabled}
                            />
                        </div>

                        {overrideEnabled ? (
                            <div className="space-y-3">
                                <PlatformModelEditor
                                    catalog={catalog}
                                    configuration={platformSeed}
                                    fallbackConfiguration={workspaceConfiguration}
                                    submitLabel="Save agent voice & model"
                                    onSave={saveV2Override}
                                    showMigrationNotice={false}
                                    onDirtyChange={setEditorDirty}
                                />
                                {catalog.locked && hasSavedModelOverride && (
                                    <Button type="button" variant="outline" onClick={removeV2Override} disabled={isRemovingOverride}>
                                        {isRemovingOverride ? "Saving..." : "Use workspace default"}
                                    </Button>
                                )}
                            </div>
                        ) : (
                            <div className="rounded-md border bg-muted/20 p-4">
                                {hasLegacyOverride ? (
                                    <p className="text-sm">
                                        This agent still runs{" "}
                                        <span className="font-medium">
                                            {isLegacyConfiguration(savedV2Override)
                                                ? describePlatformConfiguration(savedV2Override, catalog)
                                                : "an older provider setup"}
                                        </span>
                                        . Turn on the switch above to choose a managed voice and model for it,
                                        or switch it to the workspace default.
                                    </p>
                                ) : (
                                    <p className="text-sm">
                                        Using workspace default:{" "}
                                        <span className="font-medium">
                                            {describePlatformConfiguration(workspaceConfiguration, catalog)}
                                        </span>
                                    </p>
                                )}
                                <div className="mt-3 flex flex-wrap gap-2">
                                    {hasSavedModelOverride && (
                                        <Button type="button" onClick={removeV2Override} disabled={isRemovingOverride}>
                                            {isRemovingOverride ? "Saving..." : "Use workspace default"}
                                        </Button>
                                    )}
                                    {can("credentials:write") && (
                                        <Button type="button" variant="outline" asChild>
                                            <Link href="/model-configurations">Change workspace default</Link>
                                        </Button>
                                    )}
                                </div>
                            </div>
                        )}
                    </>
                )}

                {!modelConfigurationLoading && !modelConfigurationError && !platformModels && !hasOrgConfiguration && (
                    <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-4 sm:flex-row sm:items-center sm:justify-between">
                        <p className="text-sm text-muted-foreground">
                            Set up your workspace model configuration before overriding it per agent.
                        </p>
                        <Button type="button" variant="outline" size="sm" asChild>
                            <Link href="/model-configurations">Configure Models</Link>
                        </Button>
                    </div>
                )}

                {!modelConfigurationLoading && !modelConfigurationError && !platformModels && hasOrgConfiguration && legacyDefaults && organizationModelConfiguration && (
                    <>
                        <div className="flex items-center justify-between rounded-md border p-4">
                            <div className="space-y-0.5">
                                <Label htmlFor="workflow-model-v2-override" className="text-sm font-medium">
                                    Override for this agent
                                </Label>
                                <p className="text-xs text-muted-foreground">
                                    {overrideEnabled
                                        ? "This agent uses its own complete model configuration."
                                        : "This agent uses the workspace model configuration."}
                                </p>
                            </div>
                            <Switch
                                id="workflow-model-v2-override"
                                checked={overrideEnabled}
                                onCheckedChange={setOverrideEnabled}
                            />
                        </div>

                        {overrideEnabled ? (
                            <AIModelConfigurationV2Editor
                                defaults={legacyDefaults}
                                configuration={
                                    (savedV2Override as OrganizationAiModelConfigurationV2 | undefined)
                                    || (organizationModelConfiguration.configuration as OrganizationAiModelConfigurationV2 | null)
                                }
                                effectiveConfiguration={
                                    savedV2Override
                                        ? null
                                        : organizationModelConfiguration.effective_configuration
                                }
                                pricing={modelConfigurationPricing}
                                submitLabel="Save Model Override"
                                onSave={saveV2Override}
                            />
                        ) : (
                            <div className="rounded-md border bg-muted/20 p-4">
                                <p className="text-sm text-muted-foreground">
                                    Using the workspace model configuration.
                                </p>
                                {hasSavedModelOverride && (
                                    <Button
                                        type="button"
                                        className="mt-3"
                                        onClick={removeV2Override}
                                        disabled={isRemovingOverride}
                                    >
                                        {isRemovingOverride ? "Saving..." : "Save Organization Configuration"}
                                    </Button>
                                )}
                            </div>
                        )}
                    </>
                )}
            </CardContent>
        </Card>
    );
}
