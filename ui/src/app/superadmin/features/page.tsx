"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { AdminError, AdminLoading } from "@/components/platform-admin/AdminStates";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import { Button } from "@/components/ui/button";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { Switch } from "@/components/ui/switch";
import { loadFeatureFlags } from "@/lib/featureFlags";
import { type AdminFeature, platformAdminApi } from "@/lib/platformAdminApi";

/** Platform admin > Features: switch product areas for every workspace, and
 *  see the per-workspace overrides (set on a workspace's page). */
export default function PlatformAdminFeaturesPage() {
    const { data, error, setData } = useAdminData(platformAdminApi.features);
    const [saving, setSaving] = useState<string | null>(null);

    const change = async (feature: AdminFeature, enabled: boolean | null) => {
        setSaving(feature.key);
        try {
            setData(await platformAdminApi.setPlatformFeature(feature.key, enabled));
            // Your own nav follows at once; everyone else's on their next page load.
            void loadFeatureFlags();
            toast.success(
                `${feature.label}: ${enabled === null ? "back to the default" : enabled ? "on" : "off"} for every workspace without an override`,
            );
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not change the switch");
        } finally {
            setSaving(null);
        }
    };

    if (error) return <AdminError message={error} />;
    if (!data) return <AdminLoading />;

    return (
        <div className="space-y-4">
            <p className="text-sm text-ink-2">
                A switch only shows or hides the area in the app: its nav row, its pages and the pickers that lead to it.
                The API, saved data and running calls are not affected. People see a change when their app next loads;
                the redirect away from an area that is off everywhere follows within 30 seconds.
            </p>
            {data.features.map((feature) => (
                <Panel key={feature.key} className="space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                            <PanelTitle as="h2">{feature.label}</PanelTitle>
                            <PanelDescription>{feature.description}</PanelDescription>
                        </div>
                        <div className="flex items-center gap-3">
                            <label className="text-sm" htmlFor={`feature-${feature.key}`}>
                                {feature.effective_platform_value ? "On for everyone" : "Off for everyone"}
                            </label>
                            <Switch
                                id={`feature-${feature.key}`}
                                checked={feature.effective_platform_value}
                                disabled={saving === feature.key}
                                onCheckedChange={(checked) => void change(feature, checked)}
                            />
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-ink-3">
                        <span>
                            Default in code: {feature.default ? "on" : "off"}.{" "}
                            {feature.platform_value === null
                                ? "No platform-wide value is set."
                                : "A platform admin set the value above."}
                        </span>
                        {feature.platform_value !== null ? (
                            <Button
                                variant="outline"
                                size="sm"
                                disabled={saving === feature.key}
                                onClick={() => void change(feature, null)}
                            >
                                Back to the default
                            </Button>
                        ) : null}
                    </div>
                    <div className="text-sm">
                        <div className="font-medium">Workspace overrides</div>
                        {feature.overrides.length === 0 ? (
                            <p className="text-xs text-ink-3">
                                None. Set one on a workspace&apos;s page under Organisations.
                            </p>
                        ) : (
                            <ul className="mt-1 space-y-1">
                                {feature.overrides.map((override) => (
                                    <li key={override.organization_id} className="text-xs">
                                        <Link
                                            className="hover:underline"
                                            href={`/superadmin/organizations/${override.organization_id}`}
                                        >
                                            {override.organization_name || `Workspace #${override.organization_id}`}
                                        </Link>
                                        : {override.enabled ? "on" : "off"}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </Panel>
            ))}
        </div>
    );
}
