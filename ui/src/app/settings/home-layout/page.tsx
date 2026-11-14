"use client";

import { LayoutDashboard } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    clearWorkspaceHomeLayoutApiV1DashboardLayoutWorkspaceDelete,
    getHomeLayoutApiV1DashboardLayoutGet,
    saveWorkspaceHomeLayoutApiV1DashboardLayoutWorkspacePut,
} from "@/client/sdk.gen";
import type { HomeLayoutResponse } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import { SettingBlock, SettingRow, SettingsSection } from "@/components/settings/SettingsLayout";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";

/**
 * Settings > Home layout. The business owner or an admin picks which cards
 * everyone's Home starts with. Each person can still hide or pin cards for
 * themselves on Home; their own choice wins over this one.
 */
export default function HomeLayoutSettingsPage() {
    const { can, role, loading: orgLoading } = useOrgConfig();
    const { user, loading: authLoading } = useAuth();
    const allowed = can("reports:schedule");
    const fetched = useRef(false);
    const [data, setData] = useState<HomeLayoutResponse | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [hidden, setHidden] = useState<string[]>([]);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (authLoading || !user || !allowed || fetched.current) return;
        fetched.current = true;
        void getHomeLayoutApiV1DashboardLayoutGet().then((result) => {
            if (result.error || !result.data) setLoadFailed(true);
            else {
                setData(result.data);
                setHidden([...(result.data.workspace_default?.hidden ?? [])]);
            }
        });
    }, [authLoading, user, allowed]);

    if (!orgLoading && role !== null && !allowed) {
        return <NoAccess role={role} />;
    }

    const saved = data?.workspace_default ?? null;
    const changed = data !== null && [...hidden].sort().join() !== [...(saved?.hidden ?? [])].sort().join();

    async function save() {
        if (!data) return;
        setSaving(true);
        // Pinned cards stay pinned unless they are now hidden.
        const pinned = (saved?.pinned ?? []).filter((id) => !hidden.includes(id));
        const result = await saveWorkspaceHomeLayoutApiV1DashboardLayoutWorkspacePut({ body: { hidden, pinned } });
        setSaving(false);
        if (result.error || !result.data) {
            toast.error("Couldn't save the Home layout. Try again.");
            return;
        }
        setData(result.data);
        toast.success("Saved. Everyone who hasn't arranged their own Home now starts with these cards.");
    }

    async function clear() {
        setSaving(true);
        const result = await clearWorkspaceHomeLayoutApiV1DashboardLayoutWorkspaceDelete();
        setSaving(false);
        if (result.error || !result.data) {
            toast.error("Couldn't clear the Home layout. Try again.");
            return;
        }
        setData(result.data);
        setHidden([]);
        toast.success("Cleared. Home shows the standard cards again.");
    }

    return (
        <div className="page-body">
            <div className="flex w-full flex-col gap-[18px]">
                <SettingsSection
                    id="home-cards"
                    icon={LayoutDashboard}
                    tone="brand"
                    title="Cards on Home"
                    description="Which cards everyone's Home starts with. Each person can still hide or pin cards for themselves."
                >
                    {loadFailed ? (
                        <SettingBlock>
                            <p className="text-sm text-danger">Couldn&apos;t load the Home layout. Refresh to try again.</p>
                        </SettingBlock>
                    ) : !data ? (
                        <SettingBlock>
                            <Skeleton className="h-40 w-full" />
                        </SettingBlock>
                    ) : (
                        <>
                            <SettingBlock>
                                <p className="text-sm text-ink-2">
                                    {saved
                                        ? "Your workspace has its own Home layout."
                                        : "No workspace layout yet: Home shows the standard cards."}
                                </p>
                            </SettingBlock>
                            {data.cards.map((card) => {
                                const shown = !hidden.includes(card.id);
                                return (
                                    <SettingRow key={card.id} label={card.label} htmlFor={`home-card-${card.id}`} compact>
                                        <Switch
                                            id={`home-card-${card.id}`}
                                            checked={shown}
                                            disabled={saving}
                                            onCheckedChange={(on) =>
                                                setHidden((current) =>
                                                    on ? current.filter((id) => id !== card.id) : [...current, card.id],
                                                )
                                            }
                                        />
                                    </SettingRow>
                                );
                            })}
                            <SettingBlock>
                                <div className="flex flex-wrap gap-2">
                                    <Button size="sm" disabled={saving || !changed} onClick={() => void save()}>
                                        Save for everyone
                                    </Button>
                                    {saved && (
                                        <Button size="sm" variant="ghost" disabled={saving} onClick={() => void clear()}>
                                            Use the standard layout
                                        </Button>
                                    )}
                                </div>
                            </SettingBlock>
                        </>
                    )}
                </SettingsSection>
            </div>
        </div>
    );
}
