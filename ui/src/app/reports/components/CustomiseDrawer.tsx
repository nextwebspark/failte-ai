"use client";

import { GripVertical, RotateCcw } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import { resetReportLayoutApiV1OrganizationsReportsLayoutDelete, saveReportLayoutApiV1OrganizationsReportsLayoutPut } from "@/client/sdk.gen";
import type { ReportCardView, ReportLayoutView } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import { moveItem } from "../reportView";

const SAVE_FAILED = "Couldn't save your report. Please try again.";

/**
 * Customise the report: switch cards on or off, drag them (or use the arrow
 * keys on a card's handle) into order, tick the ones that go in the email,
 * and give an average for the money estimate. Saved for the whole business.
 */
export function CustomiseDrawer({
    open,
    onOpenChange,
    layout,
    packLabel,
    workflowId,
    onSaved,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    layout: ReportLayoutView;
    packLabel: string;
    workflowId: number | null;
    onSaved: (layout: ReportLayoutView) => void;
}) {
    const [cards, setCards] = useState<ReportCardView[]>(layout.cards);
    const [average, setAverage] = useState(layout.average ? String(Number(layout.average)) : "");
    const [saving, setSaving] = useState(false);
    const [dragging, setDragging] = useState<number | null>(null);
    const [announce, setAnnounce] = useState("");
    const handles = useRef<(HTMLButtonElement | null)[]>([]);
    const id = useId();

    useEffect(() => {
        if (open) {
            setCards(layout.cards);
            setAverage(layout.average ? String(Number(layout.average)) : "");
        }
    }, [open, layout]);

    const update = (key: string, change: Partial<ReportCardView>) =>
        setCards((all) => all.map((c) => (c.key === key ? { ...c, ...change } : c)));

    const move = (from: number, to: number, focus = false) => {
        if (to < 0 || to >= cards.length) return;
        setCards((all) => moveItem(all, from, to));
        setAnnounce(`${cards[from].title} moved to position ${to + 1} of ${cards.length}`);
        if (focus) requestAnimationFrame(() => handles.current[to]?.focus());
    };

    const averageValue = average.trim() === "" ? null : Number(average.replace(",", "."));
    const averageInvalid = averageValue !== null && (!Number.isFinite(averageValue) || averageValue <= 0 || averageValue > 100000);

    const save = async () => {
        if (saving || averageInvalid) return;
        setSaving(true);
        try {
            const response = await saveReportLayoutApiV1OrganizationsReportsLayoutPut({
                body: {
                    workflow_id: workflowId,
                    cards: cards.map((c) => ({ key: c.key, on: c.on, email: c.email })),
                    average: averageValue === null ? null : String(averageValue),
                },
            });
            if (response.error || !response.data) {
                toast.error(detailFromError(response.error, SAVE_FAILED));
                return;
            }
            onSaved(response.data);
            toast.success("Report saved. Everyone in your business sees it this way.");
            onOpenChange(false);
        } catch {
            toast.error(SAVE_FAILED);
        } finally {
            setSaving(false);
        }
    };

    const reset = async () => {
        if (saving) return;
        setSaving(true);
        try {
            const response = await resetReportLayoutApiV1OrganizationsReportsLayoutDelete({
                query: workflowId ? { workflow_id: workflowId } : undefined,
            });
            if (response.error || !response.data) {
                toast.error(detailFromError(response.error, SAVE_FAILED));
                return;
            }
            onSaved(response.data);
            setCards(response.data.cards);
            toast.success(`Back to the ${packLabel} pack.`);
        } catch {
            toast.error(SAVE_FAILED);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Sheet open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
            <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-[460px]">
                <SheetHeader className="border-b border-line px-5 py-4">
                    <SheetTitle className="font-display text-title">Customise this report</SheetTitle>
                    <SheetDescription className="text-caption">
                        Drag to reorder, or focus a handle and use the arrow keys. Switch cards on or off and choose what goes in the
                        email.
                    </SheetDescription>
                </SheetHeader>
                <div className="flex-1 overflow-y-auto px-5 py-4">
                    <p className="sr-only" aria-live="polite">
                        {announce}
                    </p>
                    <ol className="flex flex-col" aria-label="Report cards, in order">
                        {cards.map((card, index) => {
                            const needsAverage = card.estimate && !averageValue;
                            return (
                                <li
                                    key={card.key}
                                    draggable
                                    onDragStart={(e) => {
                                        setDragging(index);
                                        e.dataTransfer.effectAllowed = "move";
                                    }}
                                    onDragOver={(e) => {
                                        e.preventDefault();
                                        if (dragging !== null && dragging !== index) {
                                            move(dragging, index);
                                            setDragging(index);
                                        }
                                    }}
                                    onDragEnd={() => setDragging(null)}
                                    className={cn(
                                        "flex items-center gap-2 border-b border-line-soft py-2.5",
                                        dragging === index && "rounded-lg bg-panel-2 opacity-80",
                                    )}
                                >
                                    <button
                                        type="button"
                                        ref={(el) => {
                                            handles.current[index] = el;
                                        }}
                                        aria-label={`Move ${card.title}, position ${index + 1} of ${cards.length}. Use the up and down arrow keys.`}
                                        onKeyDown={(e) => {
                                            if (e.key === "ArrowUp") {
                                                e.preventDefault();
                                                move(index, index - 1, true);
                                            } else if (e.key === "ArrowDown") {
                                                e.preventDefault();
                                                move(index, index + 1, true);
                                            }
                                        }}
                                        className="flex size-8 flex-none cursor-grab items-center justify-center rounded-md text-ink-3 outline-none hover:bg-panel-2 focus-visible:ring-2 focus-visible:ring-ring/50 active:cursor-grabbing"
                                    >
                                        <GripVertical className="size-4" aria-hidden />
                                    </button>
                                    <div className="min-w-0 flex-1">
                                        <Label htmlFor={`${id}-${card.key}-on`} className={cn("text-body font-normal", !card.on && "text-ink-3")}>
                                            {card.title}
                                        </Label>
                                        {needsAverage ? (
                                            <p className="text-meta text-ink-3">Shows once you give your average below</p>
                                        ) : null}
                                    </div>
                                    <label className="flex flex-none items-center gap-1.5 text-meta text-ink-2">
                                        <Checkbox
                                            checked={card.email}
                                            onCheckedChange={(checked) => update(card.key, { email: checked === true })}
                                            aria-label={`Send ${card.title} in the email`}
                                        />
                                        in email
                                    </label>
                                    <Switch
                                        id={`${id}-${card.key}-on`}
                                        checked={card.on}
                                        onCheckedChange={(on) => update(card.key, { on })}
                                        aria-label={`Show ${card.title}`}
                                    />
                                </li>
                            );
                        })}
                    </ol>
                    {layout.value_unit ? (
                        <div className="mt-5 rounded-xl border border-line bg-panel-2 px-4 py-4">
                            <Label htmlFor={`${id}-average`} className="text-body font-semibold">
                                {layout.value_label}
                            </Label>
                            <p className="mt-1 text-caption text-ink-3">
                                Only you know this. With it, the report shows an estimate, labelled as one, with the sum written out.
                                Leave it empty to show no money at all.
                            </p>
                            <div className="mt-2 flex items-center gap-2">
                                <span className="text-body text-ink-2" aria-hidden>
                                    €
                                </span>
                                <Input
                                    id={`${id}-average`}
                                    inputMode="decimal"
                                    value={average}
                                    onChange={(e) => setAverage(e.target.value)}
                                    placeholder="e.g. 35"
                                    className="h-10 max-w-[140px]"
                                    aria-invalid={averageInvalid}
                                />
                                <span className="text-caption text-ink-3">per {layout.value_unit}</span>
                            </div>
                            {averageInvalid ? (
                                <p className="mt-1 text-caption text-destructive">Enter an amount between €0 and €100,000.</p>
                            ) : null}
                        </div>
                    ) : null}
                    <p className="mt-4 text-caption text-ink-3">
                        Saved for your business, so you and your staff see the same report.
                        {layout.updated_by ? ` Last changed by ${layout.updated_by}.` : ""}
                    </p>
                </div>
                <SheetFooter className="flex-row flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3">
                    <Button variant="ghost" onClick={reset} disabled={saving} className="h-10">
                        <RotateCcw aria-hidden />
                        Reset to the {packLabel} pack
                    </Button>
                    <div className="flex gap-2">
                        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving} className="h-10">
                            Cancel
                        </Button>
                        <Button onClick={save} disabled={saving || averageInvalid} className="h-10">
                            {saving ? "Saving…" : "Save"}
                        </Button>
                    </div>
                </SheetFooter>
            </SheetContent>
        </Sheet>
    );
}
