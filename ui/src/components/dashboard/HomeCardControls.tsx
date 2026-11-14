"use client";

import { ChevronDown, Eye, EyeOff, MoreHorizontal, Pin, PinOff, RotateCcw, Users } from "lucide-react";
import Link from "next/link";
import { createContext, type ReactNode, useContext } from "react";

import { Button } from "@/components/ui/button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { HOME_CARD_LABELS, type HomeCardId, isHidden, isPinned, type Layout } from "./homeLayout";

/**
 * What a Home card needs to offer "Hide card" and "Pin to top". Provided by
 * HomeDashboard; a card rendered without it (elsewhere, or in a test) simply
 * has no menu.
 */
type CardControls = {
    layout: Layout;
    hide: (id: HomeCardId) => void;
    unhide: (id: HomeCardId) => void;
    pin: (id: HomeCardId) => void;
    unpin: (id: HomeCardId) => void;
};

const CardControlsContext = createContext<CardControls | null>(null);

export function CardControlsProvider({ value, children }: { value: CardControls | null; children: ReactNode }) {
    return <CardControlsContext.Provider value={value}>{children}</CardControlsContext.Provider>;
}

/** Whether a card is showing only because "Show hidden" is on. */
export function useCardHidden(id: HomeCardId | undefined): boolean {
    const controls = useContext(CardControlsContext);
    return Boolean(id && controls && isHidden(controls.layout, id));
}

/** The small menu in a card's header: hide it, or pin it to the top. */
export function CardMenu({ id }: { id: HomeCardId }) {
    const controls = useContext(CardControlsContext);
    if (!controls) return null;
    const label = HOME_CARD_LABELS[id];
    if (isHidden(controls.layout, id)) {
        return (
            <Button variant="outline" size="sm" className="h-7 gap-1.5 px-2 text-caption" onClick={() => controls.unhide(id)}>
                <Eye className="size-3.5" aria-hidden />
                Unhide
                <span className="sr-only"> {label}</span>
            </Button>
        );
    }
    const pinned = isPinned(controls.layout, id);
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0 text-ink-3 hover:text-foreground"
                    aria-label={`Card options: ${label}`}
                >
                    <MoreHorizontal className="size-4" aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
                {pinned ? (
                    <DropdownMenuItem onSelect={() => controls.unpin(id)}>
                        <PinOff aria-hidden />
                        Unpin
                    </DropdownMenuItem>
                ) : (
                    <DropdownMenuItem onSelect={() => controls.pin(id)}>
                        <Pin aria-hidden />
                        Pin to top
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => controls.hide(id)}>
                    <EyeOff aria-hidden />
                    Hide card
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/**
 * A block without a card header of its own (the call numbers, the quick
 * links): a slim label row carries its menu. Dimmed while it is only shown
 * because "Show hidden" is on.
 */
export function CardSlot({ id, children }: { id: HomeCardId; children: ReactNode }) {
    const controls = useContext(CardControlsContext);
    const hidden = useCardHidden(id);
    if (!controls) return <>{children}</>;
    return (
        <section aria-label={HOME_CARD_LABELS[id]} className={cn("min-w-0", hidden && "opacity-60")}>
            <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
                <span className="text-meta font-semibold uppercase tracking-[0.06em] text-ink-3">{HOME_CARD_LABELS[id]}</span>
                <CardMenu id={id} />
            </div>
            {children}
        </section>
    );
}

/**
 * Next to Refresh: show the hidden cards again (dimmed, each with Unhide),
 * go back to the workspace's layout, and for admins, make this layout the
 * workspace's default.
 */
export function LayoutToolbar({
    hiddenCount,
    showHidden,
    onToggleHidden,
    canReset,
    onReset,
    canSetWorkspaceDefault,
    hasWorkspaceDefault,
    onSaveWorkspaceDefault,
    onClearWorkspaceDefault,
}: {
    hiddenCount: number;
    showHidden: boolean;
    onToggleHidden: () => void;
    canReset: boolean;
    onReset: () => void;
    canSetWorkspaceDefault: boolean;
    hasWorkspaceDefault: boolean;
    onSaveWorkspaceDefault: () => void;
    onClearWorkspaceDefault: () => void;
}) {
    return (
        <>
            {(hiddenCount > 0 || showHidden) && (
                <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 gap-1.5 px-2 text-caption"
                    aria-pressed={showHidden}
                    onClick={onToggleHidden}
                >
                    {showHidden ? <EyeOff className="size-3.5" aria-hidden /> : <Eye className="size-3.5" aria-hidden />}
                    {showHidden ? "Hide them again" : `Show hidden (${hiddenCount})`}
                </Button>
            )}
            {canReset && (
                <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-caption" onClick={onReset}>
                    <RotateCcw className="size-3.5" aria-hidden />
                    Reset layout
                </Button>
            )}
            {canSetWorkspaceDefault && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-caption">
                            <Users className="size-3.5" aria-hidden />
                            Workspace default
                            <ChevronDown className="size-3.5" aria-hidden />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-72">
                        <DropdownMenuLabel className="text-caption font-normal text-ink-3">
                            What members see until they arrange their own Home
                        </DropdownMenuLabel>
                        <DropdownMenuItem onSelect={onSaveWorkspaceDefault}>Use this layout for everyone</DropdownMenuItem>
                        {hasWorkspaceDefault && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem onSelect={onClearWorkspaceDefault}>Clear the workspace default</DropdownMenuItem>
                            </>
                        )}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem asChild>
                            <Link href="/settings/home-layout">Choose cards in Settings</Link>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </>
    );
}
