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
