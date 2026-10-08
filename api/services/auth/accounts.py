"""Local-auth account flows: password signup/login, email verification,
password reset and Google sign-in.

Every path that proves inbox ownership (verify link, reset link, invite link,
verified Google email) ends in ``_onboard``, which claims the address's
pending invitations and makes sure the user has an organization.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from loguru import logger

from api.db.account_client import AuthAccount
from api.enums import TokenPurpose
from api.errors.account import (
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    OAuthLoginError,
    SignupDisabledError,
)
from api.services.auth.oauth.base import OAuthIdentity
from api.services.email.base import EmailDeliveryError, EmailMessage, EmailSender
from api.services.email.templates import password_reset_message, verify_email_message
from api.services.invitations.service import InvitationService
from api.services.rate_limit import RateLimiter
from api.utils.clock import Clock
from api.utils.secure_token import hash_token, issue_token

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=60)
# Per address, for emails anyone can trigger (resend verification, reset).
ACCOUNT_EMAIL_LIMIT = 3
ACCOUNT_EMAIL_WINDOW = timedelta(minutes=15)

PasswordHasher = Callable[[str], str]
PasswordVerifier = Callable[[str, str], bool]
SessionIssuer = Callable[[int, str], str]
OrganizationEnsurer = Callable[[int, str], Awaitable[int]]


class AccountStore(Protocol):
    async def get_account(self, user_id: int) -> AuthAccount | None: ...

    async def get_account_by_email(self, email: str) -> AuthAccount | None: ...

    async def get_account_by_google_sub(
        self, google_sub: str
    ) -> AuthAccount | None: ...

    async def create_account(
        self,
        *,
        email: str,
        name: str | None,
        password_hash: str | None,
        email_verified_at: datetime | None,
        google_sub: str | None = None,
        avatar_url: str | None = None,
    ) -> AuthAccount: ...

    async def link_google_account(
        self,
        user_id: int,
        *,
        google_sub: str,
        avatar_url: str | None,
        verified_at: datetime,
        revoke_credentials: bool,
    ) -> AuthAccount: ...

    async def mark_email_verified(
        self, user_id: int, verified_at: datetime
    ) -> None: ...

    async def set_password_hash(self, user_id: int, password_hash: str) -> None: ...

    async def issue_user_token(
        self,
        *,
        user_id: int,
        purpose: TokenPurpose,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None: ...

    async def consume_user_token(
        self, *, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class AccountPolicy:
    signup_enabled: bool
    require_email_verification: bool
    app_url: str


@dataclass(frozen=True, slots=True)
class Session:
    """A logged-in user: the JWT for the API plus who it belongs to."""

    token: str
    account: AuthAccount
    organization_id: int


@dataclass(frozen=True, slots=True)
class SignupOutcome:
    account: AuthAccount
    # None when the user must verify their email before logging in.
    session: Session | None


@dataclass(frozen=True, slots=True)
class PasswordCredentials:
    email: str
    password: str


class AccountService:
    def __init__(
        self,
        *,
        store: AccountStore,
        invitations: InvitationService,
        email_sender: EmailSender,
        clock: Clock,
        policy: AccountPolicy,
        hash_password: PasswordHasher,
        verify_password: PasswordVerifier,
        issue_session_token: SessionIssuer,
        ensure_organization: OrganizationEnsurer,
        rate_limiter: RateLimiter,
    ) -> None:
        self._store = store
        self._invitations = invitations
        self._email = email_sender
        self._clock = clock
        self._policy = policy
        self._hash_password = hash_password
        self._verify_password = verify_password
        self._issue_session_token = issue_session_token
        self._ensure_organization = ensure_organization
        self._limiter = rate_limiter
        self._app_url = policy.app_url.rstrip("/")

    # -- password accounts ---------------------------------------------------

    async def signup(
        self,
        credentials: PasswordCredentials,
        *,
        name: str | None,
        invite_token: str | None,
    ) -> SignupOutcome:
        email = credentials.email.strip().lower()
        if invite_token:
            # Validate before creating anything so a bad link leaves no account.
            await self._invitations.require_acceptable(invite_token, email)
        elif not await self._may_sign_up(email):
            raise SignupDisabledError()

        if await self._store.get_account_by_email(email):
            raise EmailAlreadyRegisteredError()

        # Only the invite link proves this inbox belongs to the person signing
        # up. Turning verification off lets them in without proof; it does not
        # make the address verified.
        proven = bool(invite_token)
        account = await self._store.create_account(
            email=email,
            name=name,
            password_hash=self._hash_password(credentials.password),
            email_verified_at=self._clock.now() if proven else None,
        )
        if invite_token:
            await self._invitations.accept(
                token=invite_token, user_id=account.user_id, email=email
            )
        if not proven and self._policy.require_email_verification:
            await self._send_verification(account)
            return SignupOutcome(account=account, session=None)
        return SignupOutcome(account=account, session=await self._onboard(account))

    async def login(self, credentials: PasswordCredentials) -> Session:
        account = await self._store.get_account_by_email(credentials.email.strip())
        if (
            account is None
            or account.password_hash is None
            or not self._verify_password(credentials.password, account.password_hash)
        ):
            raise InvalidCredentialsError()
        if self._policy.require_email_verification and not account.is_email_verified:
            raise EmailNotVerifiedError()
        return await self._onboard(account)

    # -- email verification ----------------------------------------------------

    async def verify_email(self, token: str) -> Session:
        now = self._clock.now()
        user_id = await self._store.consume_user_token(
            token_hash=hash_token(token),
            purpose=TokenPurpose.EMAIL_VERIFICATION,
            now=now,
        )
        await self._store.mark_email_verified(user_id, now)
        return await self._onboard(await self._require_account(user_id))

    async def resend_verification(self, email: str) -> None:
        """Always succeeds silently so callers can't probe which emails exist."""
        account = await self._store.get_account_by_email(email.strip())
        if account is None or account.is_email_verified:
            return
        if not await self._may_email(TokenPurpose.EMAIL_VERIFICATION, account):
            return
        await self._send_verification(account)

    # -- password reset ----------------------------------------------------------

    async def request_password_reset(self, email: str) -> None:
        """Always succeeds silently so callers can't probe which emails exist."""
        account = await self._store.get_account_by_email(email.strip())
        if account is None or account.email is None:
            return
        if not await self._may_email(TokenPurpose.PASSWORD_RESET, account):
            return
        now = self._clock.now()
        token = issue_token()
        await self._store.issue_user_token(
            user_id=account.user_id,
            purpose=TokenPurpose.PASSWORD_RESET,
            token_hash=token.digest,
            expires_at=now + PASSWORD_RESET_TTL,
            now=now,
        )
        await self._send(
            password_reset_message(
                to=account.email,
                reset_url=f"{self._app_url}/auth/reset-password?token={token.raw}",
                expires_in_minutes=int(PASSWORD_RESET_TTL.total_seconds() // 60),
            )
        )

    async def reset_password(self, token: str, new_password: str) -> Session:
        now = self._clock.now()
        user_id = await self._store.consume_user_token(
            token_hash=hash_token(token), purpose=TokenPurpose.PASSWORD_RESET, now=now
        )
        await self._store.set_password_hash(user_id, self._hash_password(new_password))
        # The link reached the inbox, which also proves the address.
        await self._store.mark_email_verified(user_id, now)
        return await self._onboard(await self._require_account(user_id))

    # -- Google ----------------------------------------------------------------

    async def login_with_google(
        self, identity: OAuthIdentity, *, invite_token: str | None
    ) -> Session:
        if not identity.email_verified:
            raise OAuthLoginError("Your Google email address is not verified")
        now = self._clock.now()

        account = await self._store.get_account_by_google_sub(identity.subject)
        if account is None:
            existing = await self._store.get_account_by_email(identity.email)
            if existing is not None:
                if existing.google_sub and existing.google_sub != identity.subject:
                    raise OAuthLoginError(
                        "This email is linked to a different Google account"
                    )
                # If the address was never verified, whoever registered it may
                # not own the inbox: drop their password and pending links so
                # only the Google identity (the proven owner) keeps access.
                account = await self._store.link_google_account(
                    existing.user_id,
                    google_sub=identity.subject,
                    avatar_url=identity.picture,
                    verified_at=now,
                    revoke_credentials=not existing.is_email_verified,
                )
            else:
                if invite_token:
                    await self._invitations.require_acceptable(
                        invite_token, identity.email
                    )
                elif not await self._may_sign_up(identity.email):
                    raise SignupDisabledError()
                account = await self._store.create_account(
                    email=identity.email,
                    name=identity.name,
                    password_hash=None,
                    email_verified_at=now,
                    google_sub=identity.subject,
                    avatar_url=identity.picture,
                )

        if invite_token:
            await self._invitations.accept(
                token=invite_token, user_id=account.user_id, email=identity.email
            )
        return await self._onboard(account)

    # -- internals ---------------------------------------------------------------

    async def _may_sign_up(self, email: str) -> bool:
        if self._policy.signup_enabled:
            return True
        # An open invitation lets the address sign up while signup is closed,
        # but only when it will have to prove inbox ownership before it can
        # claim anything.
        return (
            self._policy.require_email_verification
            and await self._invitations.has_open_invitation(email)
        )

    async def _may_email(self, purpose: TokenPurpose, account: AuthAccount) -> bool:
        """Silently drop repeat requests: telling the caller would reveal that
        the address has an account."""
        return await self._limiter.allow(
            f"account-email:{purpose}:{account.user_id}",
            limit=ACCOUNT_EMAIL_LIMIT,
            window=ACCOUNT_EMAIL_WINDOW,
        )

    async def _onboard(self, account: AuthAccount) -> Session:
        # Joining invited organizations requires proof the inbox is theirs.
        if account.email and account.is_email_verified:
            await self._invitations.claim_pending(
                user_id=account.user_id,
                verified_email=account.email,
                select_latest=account.selected_organization_id is None,
            )
        organization_id = await self._ensure_organization(
            account.user_id, account.provider_id
        )
        refreshed = await self._require_account(account.user_id)
        return Session(
            token=self._issue_session_token(refreshed.user_id, refreshed.email or ""),
            account=refreshed,
            organization_id=organization_id,
        )

    async def _send_verification(self, account: AuthAccount) -> None:
        if account.email is None:
            return
        now = self._clock.now()
        token = issue_token()
        await self._store.issue_user_token(
            user_id=account.user_id,
            purpose=TokenPurpose.EMAIL_VERIFICATION,
            token_hash=token.digest,
            expires_at=now + EMAIL_VERIFICATION_TTL,
            now=now,
        )
        await self._send(
            verify_email_message(
                to=account.email,
                verify_url=f"{self._app_url}/auth/verify-email?token={token.raw}",
                expires_in_hours=int(EMAIL_VERIFICATION_TTL.total_seconds() // 3600),
            )
        )

    async def _send(self, message: EmailMessage) -> None:
        try:
            await self._email.send(message)
        except EmailDeliveryError:
            logger.exception("Failed to send account email")

    async def _require_account(self, user_id: int) -> AuthAccount:
        account = await self._store.get_account(user_id)
        if account is None:
            raise LookupError(f"user {user_id} not found")
        return account
