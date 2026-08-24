"use client";

import { Brain, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get,
    getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet,
} from "@/client/sdk.gen";
import type {
    ModelConfigurationPricingResponse,
    OrganizationAiModelConfigurationResponse,
    OrganizationAiModelConfigurationV2,
} from "@/client/types.gen";
import {
    AIModelConfigurationV2Editor,
    type ModelConfigurationDefaultsV2,
} from "@/components/AIModelConfigurationV2Editor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";
import { fetchModelConfigurationPricing } from "@/lib/modelConfigurationPricing";
import type { WorkflowConfigurations } from "@/types/workflow-configurations";

import { AgentSectionShell } from "../components/AgentSectionShell";

const PUBLISH_WORKFLOW_REMINDER = "Publish the agent to apply the changes.";

/**
 * The organization stack this agent may override. Loaded here rather than by
 * the page so the section stays self-contained.
 */
function useOrganizationModelConfiguration() {
    const [modelConfigurationDefaults, setModelConfigurationDefaults] = useState<ModelConfigurationDefaultsV2 | null>(null);
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

            setModelConfigurationDefaults(defaultsResult.data as ModelConfigurationDefaultsV2);
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

function WorkflowModelOverridesSection({
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
    const savedV2Override = workflowConfigurations.model_configuration_v2_override;
    const hasSavedModelOverride = Boolean(savedV2Override || workflowConfigurations.model_overrides);
    const [overrideEnabled, setOverrideEnabled] = useState(Boolean(savedV2Override));
    const [isRemovingOverride, setIsRemovingOverride] = useState(false);

    useEffect(() => {
        setOverrideEnabled(Boolean(workflowConfigurations.model_configuration_v2_override));
    }, [workflowConfigurations.model_configuration_v2_override]);

    const hasOrgConfiguration = organizationModelConfiguration?.source === "organization_v2";

    const saveV2Override = async (configuration: OrganizationAiModelConfigurationV2) => {
        const nextConfigurations = withoutModelConfigurationOverrides(workflowConfigurations);
        nextConfigurations.model_configuration_v2_override = configuration;
        await onSave(nextConfigurations, workflowName);
        toast.success(`Model override saved. ${PUBLISH_WORKFLOW_REMINDER}`);
    };

    const removeV2Override = async () => {
        setIsRemovingOverride(true);
        try {
            await onSave(withoutModelConfigurationOverrides(workflowConfigurations), workflowName);
            setOverrideEnabled(false);
            toast.success(`Organization model configuration saved. ${PUBLISH_WORKFLOW_REMINDER}`);
        } finally {
            setIsRemovingOverride(false);
        }
    };

    return (
        <Card id="models">
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Brain className="h-4 w-4" />
                    Model Overrides
                </CardTitle>
                <CardDescription>
                    Override the full organization model configuration for this workflow.
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

                {!modelConfigurationLoading && !modelConfigurationError && !hasOrgConfiguration && (
                    <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-4 sm:flex-row sm:items-center sm:justify-between">
                        <p className="text-sm text-muted-foreground">
                            Set up your organization model configuration before overriding it per workflow.
                        </p>
                        <Button type="button" variant="outline" size="sm" asChild>
                            <Link href="/model-configurations">Configure Models</Link>
                        </Button>
                    </div>
                )}

                {!modelConfigurationLoading && !modelConfigurationError && hasOrgConfiguration && modelConfigurationDefaults && organizationModelConfiguration && (
                    <>
                        <div className="flex items-center justify-between rounded-md border p-4">
                            <div className="space-y-0.5">
                                <Label htmlFor="workflow-model-v2-override" className="text-sm font-medium">
                                    Override for this workflow
                                </Label>
                                <p className="text-xs text-muted-foreground">
                                    {overrideEnabled
                                        ? "This workflow uses its own complete model configuration."
                                        : "This workflow uses the organization model configuration."}
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
                                defaults={modelConfigurationDefaults}
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
                                    Using organization model configuration.
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

/**
 * "Model and voice" — the canvas's Configure section for the stack this agent
 * speaks with (app-doc/claude-design/Failte AI v2.dc.html). The workspace-wide
 * stack lives at /model-configurations; this screen is where one agent departs
 * from it.
 */
export default function AgentModelAndVoicePage() {
    return (
        <AgentSectionShell>
            {({ workflowConfigurations, workflowName, saveWorkflowConfigurations }) => (
                <div className="page-body max-w-4xl space-y-6">
                    <WorkflowModelOverridesSection
                        workflowConfigurations={workflowConfigurations}
                        workflowName={workflowName}
                        onSave={saveWorkflowConfigurations}
                    />
                </div>
            )}
        </AgentSectionShell>
    );
}
