/**
 * The platform admin API (/api/v1/superuser/admin/*, /superuser/billing/*).
 *
 * These routes are internal tools and are left out of the OpenAPI schema (like
 * the existing superuser billing routes), so they have no generated SDK
 * functions: this module calls them through the shared generated client, which
 * adds the signed-in user's token. Types mirror api/schemas/platform_admin.py.
 */
import { client } from "@/client/client.gen";
import { detailFromError } from "@/lib/apiError";

// Money arrives as decimal strings (Pydantic Decimal).
type Money = string;

export type AdminFeature = {
    key: string;
    label: string;
    description: string;
    default: boolean;
    platform_value: boolean | null;
    effective_platform_value: boolean;
    overrides: { organization_id: number; organization_name: string | null; enabled: boolean; updated_at: string }[];
};

export type AdminOrganization = {
    id: number;
    name: string | null;
    created_at: string | null;
    status: "active" | "deletion_scheduled" | "erased";
    members_count: number;
    last_call_at: string | null;
    plan: "payg" | "done_for_you" | "enterprise" | null;
    balance_eur: Money | null;
    credit_limit_eur: Money | null;
    price_per_minute_override_eur: Money | null;
    effective_price_per_minute_eur: Money;
    concurrency_limit: number | null;
    effective_concurrency_limit: number;
};

export type AdminRun = {
    id: number;
    organization_id: number | null;
    organization_name: string | null;
    workflow_id: number;
    workflow_name: string | null;
    mode: string;
    call_type: string | null;
    state: string;
    call_status: string | null;
    duration_seconds: number | null;
    created_at: string | null;
};

export type AdminLedgerEntry = {
    id: number;
    entry_type: string;
    amount_eur: Money;
    balance_after_eur: Money;
    description: string | null;
    workflow_run_id: number | null;
    created_by: number | null;
    created_at: string;
};

export type AdminOrganizationDetail = {
    organization: AdminOrganization;
    members: {
        user_id: number;
        email: string | null;
        name: string | null;
        role: string;
        is_platform_admin: boolean;
        email_verified: boolean;
        joined_at: string | null;
    }[];
    recent_calls: AdminRun[];
    ledger: AdminLedgerEntry[] | null;
    ledger_total: number;
    features: Record<string, boolean>;
    feature_overrides: Record<string, boolean>;
};

export type AdminUser = {
    id: number;
    email: string | null;
    name: string | null;
    is_platform_admin: boolean;
    email_verified: boolean;
    created_at: string | null;
    memberships: { organization_id: number; organization_name: string | null; role: string }[];
};

export type Paged<T, K extends string> = Record<K, T[]> & { total: number; page: number; limit: number };

export type AdminHealth = {
    generated_at: string;
    checks: { id: string; label: string; status: "ok" | "warning" | "problem"; detail: string }[];
    failed_calls_24h: number;
    stuck_runs_24h: number;
    stuck_runs: AdminRun[];
    connections: {
        checked: boolean;
        organizations_checked: number;
        problems: {
            organization_id: number;
            organization_name: string | null;
            connection_id: string;
            provider: string;
            account_label: string | null;
            last_error: string | null;
            error_code: string | null;
        }[];
        note: string | null;
    };
};

export type AdminOverview = {
    generated_at: string;
    users_total: number;
    users_new_7d: number;
    users_new_30d: number;
    users_new_month: number;
    organizations_total: number;
    organizations_new_month: number;
    active_organizations_7d: number;
    active_organizations_30d: number;
    calls_7d: number;
    calls_month: number;
    minutes_month: number;
    revenue: {
        month: string;
        available: boolean;
        note: string | null;
        revenue_eur: Money;
        provider_cost_eur: Money;
        margin_eur: Money;
        margin_percent: Money | null;
        charged_calls: number;
        uncosted_calls: number;
    };
};

export type AdminAuditEntry = {
    id: number;
    created_at: string;
    action: string;
    actor_user_id: number | null;
    actor_email: string | null;
    organization_id: number | null;
    organization_name: string | null;
    target_user_id: number | null;
    target_user_email: string | null;
    details: Record<string, unknown>;
};

type Query = Record<string, string | number | boolean | undefined | null>;

function cleanQuery(query?: Query): Record<string, string | number | boolean> | undefined {
    if (!query) return undefined;
    const entries = Object.entries(query).filter(
        (entry): entry is [string, string | number | boolean] => entry[1] !== undefined && entry[1] !== null && entry[1] !== "",
    );
    return Object.fromEntries(entries);
}

async function call<T>(
    method: "get" | "put" | "patch" | "post",
    url: string,
    options: { query?: Query; body?: unknown } = {},
): Promise<T> {
    const response = await client[method]({
        url,
        query: cleanQuery(options.query),
        ...(options.body !== undefined
            ? { body: options.body, headers: { "Content-Type": "application/json" } }
            : {}),
    });
    if (response.error !== undefined || response.data === undefined) {
        throw new Error(detailFromError(response.error, `Request failed (${response.response?.status ?? "no response"})`));
    }
    return response.data as T;
}

const ADMIN = "/api/v1/superuser/admin";
const BILLING = "/api/v1/superuser/billing";

export const platformAdminApi = {
    overview: () => call<AdminOverview>("get", `${ADMIN}/overview`),
    health: () => call<AdminHealth>("get", `${ADMIN}/health`),
    features: () => call<{ features: AdminFeature[] }>("get", `${ADMIN}/features`),
    setPlatformFeature: (feature: string, enabled: boolean | null) =>
        call<{ features: AdminFeature[] }>("put", `${ADMIN}/features/${feature}`, { body: { enabled } }),
    setOrganizationFeature: (feature: string, organizationId: number, enabled: boolean | null) =>
        call<{ features: AdminFeature[] }>("put", `${ADMIN}/features/${feature}/organizations/${organizationId}`, {
            body: { enabled },
        }),
    organizations: (query: { search?: string; page?: number; limit?: number }) =>
        call<Paged<AdminOrganization, "organizations"> & { default_concurrency_limit: number }>(
            "get",
            `${ADMIN}/organizations`,
            { query },
        ),
    organization: (organizationId: number) =>
        call<AdminOrganizationDetail>("get", `${ADMIN}/organizations/${organizationId}`),
    setConcurrencyLimit: (organizationId: number, limit: number | null) =>
        call<{ concurrency_limit: number | null; effective_concurrency_limit: number }>(
            "put",
            `${ADMIN}/organizations/${organizationId}/concurrency-limit`,
            { body: { limit } },
        ),
    users: (query: { search?: string; platform_admins_only?: boolean; page?: number; limit?: number }) =>
        call<Paged<AdminUser, "users"> & { impersonation_available: boolean; impersonation_note: string | null }>(
            "get",
            `${ADMIN}/users`,
            { query },
        ),
    setPlatformAdmin: (userId: number, isPlatformAdmin: boolean) =>
        call<{ changed: boolean }>("put", `${ADMIN}/users/${userId}/platform-admin`, {
            body: { is_platform_admin: isPlatformAdmin },
        }),
    auditLog: (query: { organization_id?: number; action?: string; page?: number; limit?: number }) =>
        call<Paged<AdminAuditEntry, "entries">>("get", `${ADMIN}/audit-log`, { query }),
    // Billing (Stripe billing only; the API answers 404 otherwise).
    updateBilling: (
        organizationId: number,
        changes: { plan?: string; price_per_minute_eur?: string | null; credit_limit_eur?: string },
    ) => call<unknown>("patch", `${BILLING}/organizations/${organizationId}`, { body: changes }),
    adjustBalance: (organizationId: number, body: { entry_type: "adjustment" | "refund"; amount_eur: string; description: string }) =>
        call<unknown>("post", `${BILLING}/organizations/${organizationId}/adjustments`, { body }),
};
