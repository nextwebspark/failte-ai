"use client";

import {
    Building2,
    ChevronLeft,
    ChevronRight,
    CreditCard,
    Euro,
    FileText,
    RefreshCw,
    Wrench,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    createBillingPortalApiV1BillingPortalPost,
    createSetupFeeApiV1BillingSetupFeePost,
    createTopUpApiV1BillingTopUpPost,
    getBillingAccountApiV1BillingAccountGet,
    getBillingLedgerApiV1BillingLedgerGet,
} from "@/client/sdk.gen";
import type {
    BillingAccountResponse,
    BillingLedgerEntryType,
    BillingLedgerResponse,
    BillingPlan,
} from "@/client/types.gen";
import { PageActions } from "@/components/layout/PageActionsSlot";
import { SUPPORT_MAILTO } from "@/components/SupportLink";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/dateTime";

const LEDGER_PAGE_SIZE = 50;

const euroFormatter = new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency: "EUR",
});

/** Formats a decimal string from the API as euros, e.g. "19.8765" -> "€19.88". */
export const formatEur = (value: string | number | null | undefined, maximumFractionDigits = 2) => {
    const amount = Number(value ?? 0);
    if (maximumFractionDigits === 2) return euroFormatter.format(amount);
    return new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
        maximumFractionDigits,
    }).format(amount);
};

const ENTRY_LABELS: Record<BillingLedgerEntryType, string> = {
    topup: "Credit top-up",
    usage: "Call",
    setup_fee: "Done-for-you setup",
    trial_credit: "Welcome credit",
    adjustment: "Adjustment",
    refund: "Refund",
};

const PLAN_LABELS: Record<BillingPlan, string> = {
    payg: "Self-serve",
    done_for_you: "Done-for-you",
    enterprise: "Enterprise",
};

const contactHref = (contact: string | null | undefined) => {
    if (!contact) return SUPPORT_MAILTO;
    return contact.includes("@") && !contact.startsWith("mailto:") ? `mailto:${contact}` : contact;
};

const getPageFromSearchParams = (searchParams: { get: (name: string) => string | null }) => {
    const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
    return Number.isFinite(page) && page > 0 ? page : 1;
};

export function StripeBilling() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const auth = useAuth();
    const { orgContext, can, loading: orgLoading } = useOrgConfig();
    const organizationTimezone = useOrganizationTimezone();
    const canManage = can("billing:manage");

    const [account, setAccount] = useState<BillingAccountResponse | null>(null);
    const [ledger, setLedger] = useState<BillingLedgerResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [fetchError, setFetchError] = useState<string | null>(null);
    const [refreshKey, setRefreshKey] = useState(0);
    const [redirecting, setRedirecting] = useState<string | null>(null);
    const [customAmount, setCustomAmount] = useState("");
    const currentPage = getPageFromSearchParams(searchParams);
    const checkoutNotice = useRef(false);

    // Stripe returns here with ?checkout=success|cancelled.
    useEffect(() => {
        const checkout = searchParams.get("checkout");
        if (!checkout || checkoutNotice.current) return;
        checkoutNotice.current = true;
        if (checkout === "success") {
            toast.success("Payment received. Your credit will appear in a moment.");
        } else if (checkout === "cancelled") {
            toast("Checkout cancelled. You have not been charged.");
        }
        router.replace("/billing", { scroll: false });
    }, [router, searchParams]);

    useEffect(() => {
        if (auth.loading || orgLoading) return;
        if (!auth.isAuthenticated) {
            setLoading(false);
            return;
        }

        const controller = new AbortController();
        const load = async () => {
            setLoading(true);
            setFetchError(null);
            try {
                // Sequential on purpose: the first account read creates the
                // account and its welcome credit, which the ledger must include.
                const accountResponse = await getBillingAccountApiV1BillingAccountGet({
                    signal: controller.signal,
                });
                if (accountResponse.error) {
                    throw new Error(detailFromError(accountResponse.error, "Failed to load billing"));
                }
                const ledgerResponse = await getBillingLedgerApiV1BillingLedgerGet({
                    query: {
                        limit: LEDGER_PAGE_SIZE,
                        offset: (currentPage - 1) * LEDGER_PAGE_SIZE,
                    },
                    signal: controller.signal,
                });
                if (ledgerResponse.error) {
                    throw new Error(detailFromError(ledgerResponse.error, "Failed to load billing history"));
                }
                if (controller.signal.aborted) return;
                setAccount(accountResponse.data ?? null);
                setLedger(ledgerResponse.data ?? null);
            } catch (error) {
                if (controller.signal.aborted) return;
                const message = error instanceof Error ? error.message : "Failed to load billing";
                setFetchError(message);
                toast.error(message);
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        };
        void load();
        return () => controller.abort();
    }, [auth.isAuthenticated, auth.loading, orgLoading, orgContext?.organization_id, currentPage, refreshKey]);

    const redirectTo = useCallback(async (
        key: string,
        request: () => Promise<{ data?: { url: string }; error?: unknown }>,
        failure: string,
    ) => {
        setRedirecting(key);
        try {
            const response = await request();
            if (response.error || !response.data?.url) {
                throw new Error(detailFromError(response.error, failure));
            }
            window.location.href = response.data.url;
        } catch (error) {
            toast.error(error instanceof Error ? error.message : failure);
            setRedirecting(null);
        }
    }, []);

    const handleTopUp = (amount: string) => redirectTo(
        `topup:${amount}`,
        () => createTopUpApiV1BillingTopUpPost({ body: { amount_eur: amount } }),
        "Failed to open checkout",
    );

    const handleCustomTopUp = () => {
        if (!account) return;
        const amount = Number(customAmount);
        if (!Number.isFinite(amount)
            || amount < Number(account.min_topup_eur)
            || amount > Number(account.max_topup_eur)) {
            toast.error(
                `Enter an amount between ${formatEur(account.min_topup_eur)} and ${formatEur(account.max_topup_eur)}`,
            );
            return;
        }
        void handleTopUp(amount.toFixed(2));
    };

    const handleSetupFee = () => redirectTo(
        "setup",
        () => createSetupFeeApiV1BillingSetupFeePost(),
        "Failed to open checkout",
    );

    const handleInvoices = () => redirectTo(
        "portal",
        () => createBillingPortalApiV1BillingPortalPost(),
        "Failed to open invoices",
    );

    const handlePageChange = (page: number) => {
        const next = Math.max(1, page);
        router.push(next > 1 ? `/billing?page=${next}` : "/billing", { scroll: false });
    };

    if ((loading && !account && !fetchError) || orgLoading) {
        return (
            <div className="page-body space-y-6">
                <div className="grid gap-4 md:grid-cols-3">
                    <Skeleton className="h-36 rounded-lg" />
                    <Skeleton className="h-36 rounded-lg" />
                    <Skeleton className="h-36 rounded-lg" />
                </div>
                <Skeleton className="h-80 rounded-lg" />
            </div>
        );
    }

    const balance = Number(account?.balance_eur ?? 0);
    const outOfCredit = account
        ? balance + Number(account.credit_limit_eur) < Number(account.min_balance_for_call_eur)
        : false;
    const totalPages = ledger ? Math.ceil(ledger.total / LEDGER_PAGE_SIZE) : 0;

    return (
        <div className="page-body space-y-6">
            <PageActions>
                <Button variant="outline" onClick={() => setRefreshKey(value => value + 1)} disabled={loading}>
                    <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                    Refresh
                </Button>
                {canManage && (
                    <Button variant="outline" onClick={handleInvoices} disabled={redirecting !== null}>
                        <FileText className="h-4 w-4" />
                        {redirecting === "portal" ? "Opening..." : "Invoices & receipts"}
                    </Button>
                )}
            </PageActions>

            {fetchError && !account && (
                <p role="alert" className="py-8 text-center text-destructive">{fetchError}</p>
            )}

            {account && (
                <>
                    <div className="grid gap-4 md:grid-cols-3">
                        <Card>
                            <CardHeader className="pb-2">
                                <CardDescription>Credit balance</CardDescription>
                                <CardTitle className={`flex items-center gap-2 text-3xl ${outOfCredit ? "text-destructive" : ""}`}>
                                    <Euro className="h-6 w-6 text-muted-foreground" />
                                    {formatEur(account.balance_eur).replace("€", "")}
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                <p className="text-sm text-muted-foreground">
                                    {outOfCredit
                                        ? "Calls are paused until you top up."
                                        : "Prepaid, excluding VAT."}
                                    {Number(account.credit_limit_eur) > 0 && (
                                        <> Credit limit {formatEur(account.credit_limit_eur)}.</>
                                    )}
                                </p>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader className="pb-2">
                                <CardDescription>Call rate</CardDescription>
                                <CardTitle className="text-3xl">
                                    {formatEur(account.price_per_minute_eur, 4)}
                                    <span className="text-base font-normal text-muted-foreground"> / min</span>
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                <p className="text-sm text-muted-foreground">
                                    Billed per second of call time. Unanswered calls are free.
                                </p>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader className="pb-2">
                                <CardDescription>Plan</CardDescription>
                                <CardTitle className="text-3xl">{PLAN_LABELS[account.plan]}</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <p className="text-sm text-muted-foreground">
                                    {account.plan === "enterprise"
                                        ? "Custom terms, invoiced monthly."
                                        : "Pay as you go, no monthly fee."}
                                </p>
                            </CardContent>
                        </Card>
                    </div>

                    {canManage && (
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <CreditCard className="h-5 w-5" />
                                    Add credit
                                </CardTitle>
                                <CardDescription>
                                    Pay securely with Stripe. VAT is added at checkout, and a VAT
                                    invoice is emailed for every payment. EU businesses can enter
                                    their VAT number for reverse charge.
                                </CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <div className="flex flex-wrap gap-2">
                                    {account.topup_packs_eur.map(pack => (
                                        <Button
                                            key={pack}
                                            variant="outline"
                                            onClick={() => void handleTopUp(pack)}
                                            disabled={redirecting !== null}
                                        >
                                            {redirecting === `topup:${pack}` ? "Opening..." : formatEur(pack).replace(".00", "")}
                                        </Button>
                                    ))}
                                </div>
                                <div className="flex max-w-sm gap-2">
                                    <Input
                                        type="number"
                                        inputMode="decimal"
                                        min={Number(account.min_topup_eur)}
                                        max={Number(account.max_topup_eur)}
                                        step="0.01"
                                        placeholder={`Other amount (min ${formatEur(account.min_topup_eur).replace(".00", "")})`}
                                        aria-label="Custom top-up amount in euro"
                                        value={customAmount}
                                        onChange={event => setCustomAmount(event.target.value)}
                                    />
                                    <Button onClick={handleCustomTopUp} disabled={redirecting !== null || !customAmount}>
                                        Buy credit
                                    </Button>
                                </div>
                            </CardContent>
                        </Card>
                    )}

                    <div className="grid gap-4 md:grid-cols-3">
                        <Card className={account.plan === "payg" ? "border-primary" : undefined}>
                            <CardHeader>
                                <CardTitle className="flex items-center justify-between">
                                    Self-serve
                                    {account.plan === "payg" && <Badge>Current</Badge>}
                                </CardTitle>
                                <CardDescription>
                                    Build your own agents. {formatEur(account.price_per_minute_eur, 4)} per
                                    minute, no monthly fee.
                                </CardDescription>
                            </CardHeader>
                        </Card>

                        <Card className={account.plan === "done_for_you" ? "border-primary" : undefined}>
                            <CardHeader>
                                <CardTitle className="flex items-center justify-between">
                                    <span className="flex items-center gap-2">
                                        <Wrench className="h-4 w-4" />
                                        Done-for-you
                                    </span>
                                    {account.plan === "done_for_you" && <Badge>Current</Badge>}
                                </CardTitle>
                                <CardDescription>
                                    We design and build your agent for a one-time{" "}
                                    {formatEur(account.setup_fee_eur).replace(".00", "")}, including{" "}
                                    {formatEur(account.setup_fee_included_credit_eur).replace(".00", "")} of
                                    call credit. Then pay as you go.
                                </CardDescription>
                            </CardHeader>
                            {canManage && account.plan === "payg" && (
                                <CardContent>
                                    <Button onClick={handleSetupFee} disabled={redirecting !== null}>
                                        {redirecting === "setup" ? "Opening..." : "Get it built for you"}
                                    </Button>
                                </CardContent>
                            )}
                        </Card>

                        <Card className={account.plan === "enterprise" ? "border-primary" : undefined}>
                            <CardHeader>
                                <CardTitle className="flex items-center justify-between">
                                    <span className="flex items-center gap-2">
                                        <Building2 className="h-4 w-4" />
                                        Enterprise
                                    </span>
                                    {account.plan === "enterprise" && <Badge>Current</Badge>}
                                </CardTitle>
                                <CardDescription>
                                    Single sign-on, dedicated hosting and data residency, a data
                                    processing agreement and monthly support retainer, on custom rates.
                                </CardDescription>
                            </CardHeader>
                            {account.plan !== "enterprise" && (
                                <CardContent>
                                    <Button variant="outline" asChild>
                                        <a href={contactHref(account.sales_contact)}>Contact sales</a>
                                    </Button>
                                </CardContent>
                            )}
                        </Card>
                    </div>
                </>
            )}

            <Card>
                <CardHeader>
                    <CardTitle>Billing history</CardTitle>
                    <CardDescription>Every top-up, call charge and credit, newest first.</CardDescription>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <Skeleton className="h-64 w-full" />
                    ) : ledger && ledger.entries.length > 0 ? (
                        <div className="overflow-x-auto rounded-lg border bg-card shadow-sm">
                            <Table>
                                <TableHeader>
                                    <TableRow className="bg-muted/50">
                                        <TableHead>Date</TableHead>
                                        <TableHead>Activity</TableHead>
                                        <TableHead>Run</TableHead>
                                        <TableHead className="text-right">Amount</TableHead>
                                        <TableHead className="text-right">Balance</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {ledger.entries.map(entry => {
                                        const amount = Number(entry.amount_eur);
                                        return (
                                            <TableRow key={entry.id}>
                                                <TableCell>{formatDateTime(entry.created_at, organizationTimezone)}</TableCell>
                                                <TableCell>
                                                    <div className="flex flex-col gap-1">
                                                        <span className="font-medium">{ENTRY_LABELS[entry.entry_type]}</span>
                                                        {entry.description && entry.description !== ENTRY_LABELS[entry.entry_type] && (
                                                            <span className="text-xs text-muted-foreground">{entry.description}</span>
                                                        )}
                                                    </div>
                                                </TableCell>
                                                <TableCell>{entry.workflow_run_id ? `#${entry.workflow_run_id}` : "-"}</TableCell>
                                                <TableCell className={`text-right font-medium ${amount >= 0 ? "text-green-600" : "text-destructive"}`}>
                                                    {amount >= 0 ? "+" : "-"}
                                                    {formatEur(Math.abs(amount), 4)}
                                                </TableCell>
                                                <TableCell className="text-right">{formatEur(entry.balance_after_eur)}</TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        </div>
                    ) : (
                        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
                            No billing activity yet.
                        </div>
                    )}
                    {!loading && totalPages > 1 && (
                        <div className="mt-6 flex items-center justify-between">
                            <p className="text-sm text-muted-foreground">
                                Page {currentPage} of {totalPages} ({ledger?.total} entries)
                            </p>
                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handlePageChange(currentPage - 1)}
                                    disabled={currentPage <= 1}
                                >
                                    <ChevronLeft className="h-4 w-4" />
                                    Previous
                                </Button>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handlePageChange(currentPage + 1)}
                                    disabled={currentPage >= totalPages}
                                >
                                    Next
                                    <ChevronRight className="h-4 w-4" />
                                </Button>
                            </div>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
