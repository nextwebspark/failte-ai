/**
 * Which Home cards show and which come first. The layout itself is saved by
 * the API (GET/PUT/DELETE /dashboard/layout): the member's own, else the
 * workspace default, else the platform default, else the built-in one
 * (api/services/dashboard/home_layout.py). These helpers only change it.
 *
 * A card not named in a layout shows in its usual place, so a card added to
 * Home later shows until someone hides it.
 */

export type HomeCardId =
    | "get-started"
    | "tiles"
    | "attention"
    | "callers-wanted"
    | "when-called"
    | "recent-calls"
    | "your-agent"
    | "quick-links";

export const HOME_CARD_LABELS: Record<HomeCardId, string> = {
    "get-started": "Get started",
    tiles: "Call numbers",
    attention: "Needs your attention",
    "callers-wanted": "What callers wanted",
    "when-called": "When people called",
    "recent-calls": "Recent calls",
    "your-agent": "Your agent",
    "quick-links": "Quick links",
};

export type Layout = { hidden: string[]; pinned: string[] };

export const EMPTY_LAYOUT: Layout = { hidden: [], pinned: [] };

export function isHidden(layout: Layout, id: string): boolean {
    return layout.hidden.includes(id);
}

export function isPinned(layout: Layout, id: string): boolean {
    return layout.pinned.includes(id);
}

/** Hiding a card also unpins it. */
export function hideCard(layout: Layout, id: string): Layout {
    return {
        hidden: isHidden(layout, id) ? layout.hidden : [...layout.hidden, id],
        pinned: layout.pinned.filter((p) => p !== id),
    };
}

export function unhideCard(layout: Layout, id: string): Layout {
    return { ...layout, hidden: layout.hidden.filter((h) => h !== id) };
}

/** Pinning a card shows it, after the cards pinned before it. */
export function pinCard(layout: Layout, id: string): Layout {
    return {
        hidden: layout.hidden.filter((h) => h !== id),
        pinned: isPinned(layout, id) ? layout.pinned : [...layout.pinned, id],
    };
}

export function unpinCard(layout: Layout, id: string): Layout {
    return { ...layout, pinned: layout.pinned.filter((p) => p !== id) };
}

/**
 * The cards on this Home in order: pinned ones (in pin order) first, then
 * the rest in their usual order. Hidden cards are left out unless
 * `showHidden`; they then keep their usual place.
 */
export function arrangeCards<T extends string>(
    layout: Layout,
    present: readonly T[],
    showHidden: boolean,
): { pinned: T[]; rest: T[]; hiddenCount: number } {
    const shown = (id: T) => showHidden || !isHidden(layout, id);
    const pinned = layout.pinned.filter((id): id is T => (present as readonly string[]).includes(id) && !isHidden(layout, id));
    const rest = present.filter((id) => !pinned.includes(id) && shown(id));
    const hiddenCount = present.filter((id) => isHidden(layout, id)).length;
    return { pinned, rest, hiddenCount };
}
