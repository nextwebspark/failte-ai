"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { getBillingAccountApiV1BillingAccountGet } from "@/client/sdk.gen";
import type { BillingAccountResponse } from "@/client/types.gen";
import { useAppConfig } from "@/context/AppConfigContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";

// Warn once spendable credit drops below this many euro.
const LOW_BALANCE_EUR = 5;
// Re-check the balance on navigation at most this often.
const REFRESH_INTERVAL_MS = 60_000;

const euro = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });

/** Warns across the app when prepaid call credit is low or used up. */
export function LowBalanceBanner() {
    const pathname = usePathname();
    const { config } = useAppConfig();
    const auth = useAuth();
    const { orgContext, can, loading: orgLoading } = useOrgConfig();
    const [account, setAccount] = useState<BillingAccountResponse | null>(null);
    const lastFetch = useRef<{ organizationId: number | null | undefined; at: number } | null>(null);

    const enabled = config?.billingProvider === "stripe"
        && !auth.loading
        && auth.isAuthenticated
        && !orgLoading
        && can("billing:read");
    const organizationId = orgContext?.organization_id;

    useEffect(() => {
        if (!enabled) return;
        const previous = lastFetch.current;
        if (previous
            && previous.organizationId === organizationId
            && Date.now() - previous.at < REFRESH_INTERVAL_MS) {
            return;
        }
        lastFetch.current = { organizationId, at: Date.now() };

        const controller = new AbortController();
        getBillingAccountApiV1BillingAccountGet({ signal: controller.signal })
            .then(response => {
                if (!controller.signal.aborted) setAccount(response.data ?? null);
            })
            .catch(() => {
                // The banner is a convenience; the billing page reports errors.
            });
        return () => controller.abort();
    }, [enabled, organizationId, pathname]);

    if (!enabled || !account || pathname.startsWith("/billing")) return null;

    const available = Number(account.balance_eur) + Number(account.credit_limit_eur);
    if (available >= LOW_BALANCE_EUR) return null;
    const outOfCredit = available < Number(account.min_balance_for_call_eur);

    return (
        <div role="status" className="border-b border-amber/40 bg-amber-dim px-4 py-3 text-foreground">
            <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
                <p className="text-sm">
                    <span className="font-semibold">
                        {outOfCredit ? "Out of call credit." : "Call credit is running low."}
                    </span>{" "}
                    {outOfCredit
                        ? "New calls are paused until you top up."
                        : `${euro.format(Number(account.balance_eur))} left.`}{" "}
                    <Link href="/billing" className="font-medium underline underline-offset-2">
                        Add credit
                    </Link>
                </p>
            </div>
        </div>
    );
}
