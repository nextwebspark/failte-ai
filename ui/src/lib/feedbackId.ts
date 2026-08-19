/**
 * Unique ids for live-conversation feedback rows.
 *
 * These ids only need to be unique, not meaningful — but `Date.now()` alone is
 * not unique. Two events landing in the same millisecond (one failed synthesis
 * emits its pipeline error more than once) produced the same id, and React
 * dropped one of the rendered rows with a duplicate-key error.
 */

let sequence = 0;

export function feedbackId(prefix: string): string {
    return `${prefix}-${Date.now()}-${sequence++}`;
}
