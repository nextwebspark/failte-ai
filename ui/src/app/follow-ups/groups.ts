import type { FollowUpItem } from "@/client/types.gen";
import { callerWords } from "@/components/dashboard/dashboardView";

export interface CallerGroup {
    /** Unique per group, for React. */
    id: string;
    key: string;
    label: string;
    items: FollowUpItem[];
}

/** Digits only, so "+353 87 111 1111" and "+353871111111" are one caller. */
function callerKey(item: FollowUpItem): string {
    const digits = (item.caller_number || item.callback_number || "").replace(/\D/g, "");
    return digits || `call-${item.run_id}`;
}

/**
 * Runs of one caller's follow-ups, in the order the API sent them (to do:
 * the caller waiting longest first, each caller's oldest first).
 */
export function groupByCaller(items: FollowUpItem[]): CallerGroup[] {
    const groups: CallerGroup[] = [];
    for (const item of items) {
        const key = callerKey(item);
        const last = groups[groups.length - 1];
        if (last && last.key === key) {
            last.items.push(item);
        } else {
            groups.push({ id: `${key}-${groups.length}`, key, label: callerWords(item), items: [item] });
        }
    }
    return groups;
}
