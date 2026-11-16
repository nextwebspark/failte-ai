import { formatDateTime } from "@/lib/dateTime";

/** "€12.30" from a decimal string; "—" when there is none. */
export function formatEur(value: string | number | null | undefined, digits = 2): string {
    if (value === null || value === undefined || value === "") return "—";
    const amount = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(amount)) return String(value);
    return new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: digits,
        maximumFractionDigits: Math.max(digits, 4),
    }).format(amount);
}

export function formatWhen(value: string | null | undefined): string {
    return value ? formatDateTime(value) : "—";
}

export function formatSeconds(seconds: number | null | undefined): string {
    if (seconds === null || seconds === undefined) return "—";
    const total = Math.round(seconds);
    const minutes = Math.floor(total / 60);
    return minutes > 0 ? `${minutes}m ${total % 60}s` : `${total}s`;
}

export const PLAN_LABELS: Record<string, string> = {
    payg: "Pay as you go",
    done_for_you: "Done for you",
    enterprise: "Enterprise",
};

/** Plain words for an audit log action. */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
    "feature.platform_set": "Feature switched (all workspaces)",
    "feature.organization_set": "Feature switched (one workspace)",
    "billing.terms_updated": "Billing terms changed",
    "billing.balance_adjusted": "Credit added or removed",
    "organization.concurrency_limit_set": "Concurrent-call limit changed",
    "user.platform_admin_granted": "Platform admin granted",
    "user.platform_admin_revoked": "Platform admin revoked",
    "user.impersonation_started": "Impersonation started",
    "home_layout.platform_set": "Home layout default changed",
};
