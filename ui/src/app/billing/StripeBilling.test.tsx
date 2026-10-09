import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BillingPage from "./page";

const mocks = vi.hoisted(() => ({
    getAccount: vi.fn(), getLedger: vi.fn(), topUp: vi.fn(), setupFee: vi.fn(), portal: vi.fn(),
    getCredits: vi.fn(), push: vi.fn(), replace: vi.fn(),
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
    params: new URLSearchParams(),
    can: vi.fn<(...permissions: string[]) => boolean>(() => true),
}));
vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
    useSearchParams: () => mocks.params,
}));
vi.mock("@/client/sdk.gen", () => ({
    getBillingAccountApiV1BillingAccountGet: mocks.getAccount,
    getBillingLedgerApiV1BillingLedgerGet: mocks.getLedger,
    createTopUpApiV1BillingTopUpPost: mocks.topUp,
    createSetupFeeApiV1BillingSetupFeePost: mocks.setupFee,
    createBillingPortalApiV1BillingPortalPost: mocks.portal,
    getBillingCreditsApiV1OrganizationsBillingCreditsGet: mocks.getCredits,
    createMpsCreditPurchaseUrlApiV1OrganizationsUsageMpsCreditsPurchaseUrlPost: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ isAuthenticated: true, loading: false }) }));
vi.mock("@/context/AppConfigContext", () => ({
    useAppConfig: () => ({ config: { deploymentMode: "oss", billingProvider: "stripe" }, loading: false }),
}));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ orgContext: { organization_id: 42 }, can: mocks.can, loading: false }),
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({ useOrganizationTimezone: () => "Europe/Dublin" }));
vi.mock("sonner", () => ({ toast: mocks.toast }));

const account = {
    currency: "eur", plan: "payg", balance_eur: "19.8765", credit_limit_eur: "0.0000",
    price_per_minute_eur: "0.12", min_balance_for_call_eur: "0.50",
    topup_packs_eur: ["20", "50", "100", "250"], min_topup_eur: "20", max_topup_eur: "5000",
    setup_fee_eur: "550.00", setup_fee_included_credit_eur: "50.00", sales_contact: "sales@fallcha.ai",
};
const ledger = {
    entries: [{
        id: 1, entry_type: "usage", amount_eur: "-0.1800", balance_after_eur: "19.8765",
        description: "Call 9: 90s at EUR 0.12/min", workflow_run_id: 9,
        created_at: "2026-10-08T10:00:00Z",
    }],
    total: 1, limit: 50, offset: 0,
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.params = new URLSearchParams();
    mocks.can.mockReturnValue(true);
    mocks.getAccount.mockResolvedValue({ data: account });
    mocks.getLedger.mockResolvedValue({ data: ledger });
});

describe("Stripe billing page", () => {
    it("shows the EUR balance, rate and history instead of MPS credits", async () => {
        render(<BillingPage />);

        expect(await screen.findByText("19.88")).toBeTruthy();
        expect(screen.getByText("€0.12")).toBeTruthy();
        expect(screen.getByText("Call 9: 90s at EUR 0.12/min")).toBeTruthy();
        expect(screen.getByText("Contact sales").closest("a")?.getAttribute("href"))
            .toBe("mailto:sales@fallcha.ai");
        expect(mocks.getCredits).not.toHaveBeenCalled();
    });

    it("opens Stripe Checkout for a top-up pack", async () => {
        mocks.topUp.mockResolvedValue({ data: { url: "https://checkout.stripe.test/c/1" } });
        render(<BillingPage />);

        fireEvent.click(await screen.findByRole("button", { name: "€50" }));

        await waitFor(() => expect(mocks.topUp).toHaveBeenCalledWith({ body: { amount_eur: "50" } }));
    });

    it("rejects a custom amount below the minimum without calling the API", async () => {
        render(<BillingPage />);

        fireEvent.change(await screen.findByLabelText("Custom top-up amount in euro"), {
            target: { value: "5" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Buy credit" }));

        expect(mocks.topUp).not.toHaveBeenCalled();
        expect(mocks.toast.error).toHaveBeenCalled();
    });

    it("hides purchasing from members who can only read billing", async () => {
        mocks.can.mockImplementation((...permissions: string[]) => permissions.every(p => p === "billing:read"));
        render(<BillingPage />);

        await screen.findByText("19.88");
        expect(screen.queryByText("Add credit")).toBeNull();
        expect(screen.queryByRole("button", { name: "Get it built for you" })).toBeNull();
    });

    it("confirms a completed checkout and clears the query string", async () => {
        mocks.params = new URLSearchParams("checkout=success");
        render(<BillingPage />);

        await waitFor(() => expect(mocks.toast.success).toHaveBeenCalled());
        expect(mocks.replace).toHaveBeenCalledWith("/billing", { scroll: false });
    });
});
