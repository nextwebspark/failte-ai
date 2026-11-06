/**
 * Classes for the one real link in a clickable table row or card.
 *
 * The link's `::after` is stretched over the nearest positioned ancestor (give
 * the row or card `relative`), so a click anywhere on it opens the link, while
 * keyboard focus, middle-click and "open in new tab" keep working. Any other
 * control in the row needs `relative z-10` to sit above the stretched area.
 */
export const ROW_LINK =
    "rounded-sm outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring";

/** Classes for a row or card that carries a stretched ROW_LINK. */
export const ROW_LINK_CONTAINER = "relative cursor-pointer";
