"""Domain errors for sign-up, login and account recovery; see
``api.errors.domain``."""

from api.errors.domain import DomainError


class AccountError(DomainError):
    pass


class InvalidCredentialsError(AccountError):
    status_code = 401
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Invalid email or password")


class EmailNotVerifiedError(AccountError):
    status_code = 403
    code = "email_not_verified"

    def __init__(self) -> None:
        super().__init__("Verify your email address to continue")


class EmailAlreadyRegisteredError(AccountError):
    status_code = 409
    code = "email_registered"

    def __init__(self) -> None:
        super().__init__("Email already registered")


class SignupDisabledError(AccountError):
    status_code = 403
    code = "signup_disabled"

    def __init__(self) -> None:
        super().__init__("Signup is disabled")


class InvalidAccountTokenError(AccountError):
    status_code = 400
    code = "invalid_token"

    def __init__(self) -> None:
        super().__init__("This link is invalid or has expired")


class OAuthLoginError(AccountError):
    status_code = 400
    code = "oauth_failed"
