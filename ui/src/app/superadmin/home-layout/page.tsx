"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AdminError, AdminLoading } from "@/components/platform-admin/AdminStates";
import { useAdminData } from "@/components/platform-admin/useAdminData";
import { Button } from "@/components/ui/button";
import { Panel, PanelDescription, PanelTitle } from "@/components/ui/panel";
import { Switch } from "@/components/ui/switch";
import { type HomeLayoutValue, platformAdminApi } from "@/lib/platformAdminApi";

/**
 * Platform admin > Home layout: which Home cards a workspace starts with
 * when neither the member nor the workspace has arranged their own. Every
 * card stays one click away on Home ("Show hidden").
 */
export default function PlatformAdminHomeLayoutPage() {
    const { data, error, setData, reload } = useAdminData(platformAdminApi.homeLayout);
    const [draft, setDraft] = useState<HomeLayoutValue | null>(null);
    const [saving, setSaving] = useState(false);

    const current = data ? (data.layout ?? data.built_in) : null;
    useEffect(() => {
        if (current) setDraft({ hidden: [...current.hidden], pinned: [...current.pinned] });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data]);

    const save = async (layout: HomeLayoutValue | null, done: string) => {
        setSaving(true);
        try {
            setData(await platformAdminApi.setHomeLayout(layout));
            toast.success(done);
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not save the Home layout");
        } finally {
            setSaving(false);
        }
    };

    if (error) {
        return (
            <div className="space-y-3">
                <AdminError message={error} />
                <Button size="sm" variant="outline" onClick={() => void reload()}>
                    Try again
                </Button>
            </div>
        );
    }
    if (!data || !draft) return <AdminLoading />;

    const changed = JSON.stringify(draft.hidden.slice().sort()) !== JSON.stringify(current!.hidden.slice().sort());
    const toggle = (id: string, shown: boolean) =>
        setDraft((d) =>
            d && {
                hidden: shown ? d.hidden.filter((h) => h !== id) : [...d.hidden, id],
                pinned: shown ? d.pinned : d.pinned.filter((p) => p !== id),
            },
        );

    return (
        <div className="space-y-4">
            <p className="text-sm text-ink-2">
                The cards a workspace&apos;s Home shows until an admin of that workspace saves a default, or a member
                arranges their own. Hidden cards are still one click away on Home (&ldquo;Show hidden&rdquo;). Changes
                apply the next time people open Home.
            </p>
            <Panel className="space-y-4">
                <div>
                    <PanelTitle as="h2">Cards shown by default</PanelTitle>
                    <PanelDescription>
                        {data.layout
                            ? "A platform admin set this layout."
                            : "The built-in layout applies: a calm first visit (agent status, who needs a call back, recent calls and the agent)."}
                    </PanelDescription>
                </div>
                <ul className="divide-y divide-line-soft">
                    {data.cards.map((card) => {
                        const shown = !draft.hidden.includes(card.id);
                        return (
                            <li key={card.id} className="flex items-center justify-between gap-3 py-2.5">
                                <label htmlFor={`home-card-${card.id}`} className="text-sm text-foreground">
                                    {card.label}
                                </label>
                                <Switch
                                    id={`home-card-${card.id}`}
                                    checked={shown}
                                    onCheckedChange={(on) => toggle(card.id, on)}
                                    disabled={saving}
                                />
                            </li>
                        );
                    })}
                </ul>
                <div className="flex flex-wrap gap-2">
                    <Button size="sm" disabled={saving || !changed} onClick={() => void save(draft, "Home layout saved for every workspace without its own")}>
                        Save
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        disabled={saving}
                        onClick={() =>
                            void save(
                                { hidden: [], pinned: [] },
                                "Every card now shows by default",
                            )
                        }
                    >
                        Show every card
                    </Button>
                    {data.layout && (
                        <Button size="sm" variant="ghost" disabled={saving} onClick={() => void save(null, "Back to the built-in layout")}>
                            Use the built-in layout
                        </Button>
                    )}
                </div>
            </Panel>
        </div>
    );
}
