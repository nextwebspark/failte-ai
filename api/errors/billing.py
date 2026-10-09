"""Domain errors for Stripe billing; see ``api.errors.domain``."""

from api.errors.domain import DomainError


class BillingError(DomainError):
    """Base class for billing rule violations."""


class BillingNotConfiguredError(BillingError):
    status_code = 503
    code = "billing_not_configured"

    def __init__(self) -> None:
        super().__init__("Billing is not configured on this server")


class InvalidTopUpAmountError(BillingError):
    status_code = 422
    code = "invalid_topup_amount"


class CheckoutRateLimitError(BillingError):
    status_code = 429
    code = "checkout_rate_limited"

    def __init__(self) -> None:
        super().__init__("Too many checkout attempts. Please wait a few minutes.")


class SetupFeeNotAvailableError(BillingError):
    status_code = 409
    code = "setup_fee_not_available"

    def __init__(self, plan: str) -> None:
        super().__init__(
            f"The setup fee can only be bought on the pay-as-you-go plan, not {plan}"
        )
