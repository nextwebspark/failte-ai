"""Invitation lifecycle: issue, resend, revoke, preview, accept, auto-claim."""

from dataclasses import dataclass
from datetime import timedelta

from loguru import logger

from api.db.invitation_client import Invitation
from api.enums import InvitationStatus, OrgRole
from api.errors.invitations import (
    InvitationEmailMismatchError,
    InvitationNotFoundError,
    InvitationNotUsableError,
    InvitationRateLimitError,
)
from api.errors.membership import AlreadyMemberError
from api.services.auth.permissions import ROLE_LABELS
from api.services.email.base import EmailDeliveryError, EmailSender
from api.services.email.templates import invitation_email
from api.services.invitations.ports import Directory, InvitationStore
from api.utils.clock import Clock
from api.utils.secure_token import hash_token, issue_token

INVITATION_TTL = timedelta(days=7)
RATE_LIMIT_WINDOW = timedelta(hours=1)
MAX_INVITATIONS_PER_WINDOW = 50
_FALLBACK_ORG_NAME = "a Dograh workspace"


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation: Invitation
    # Returned to the inviting admin only when the email could not be
    # delivered, so they can share the link another way.
    accept_url: str | None
    email_sent: bool


@dataclass(frozen=True, slots=True)
class InvitationPreview:
    """What the holder of an invitation link may see before accepting."""

    organization_name: str
    inviter_name: str | None
    role: OrgRole
    email: str
    status: InvitationStatus


class InvitationService:
    def __init__(
        self,
        *,
        store: InvitationStore,
        directory: Directory,
        email_sender: EmailSender,
        clock: Clock,
        app_url: str,
    ) -> None:
        self._store = store
        self._directory = directory
        self._email = email_sender
        self._clock = clock
        self._app_url = app_url.rstrip("/")

    # -- admin actions -------------------------------------------------------

    async def invite(
        self, *, organization_id: int, inviter_id: int, email: str, role: OrgRole
    ) -> IssuedInvitation:
        email = email.strip().lower()
        existing = await self._directory.get_user_identity_by_email(email)
        if existing and await self._directory.get_member_role(
            existing.user_id, organization_id
        ):
            raise AlreadyMemberError()

        now = self._clock.now()
        recent = await self._store.count_invitations_created_since(
            organization_id, now - RATE_LIMIT_WINDOW
        )
        if recent >= MAX_INVITATIONS_PER_WINDOW:
            raise InvitationRateLimitError()

        token = issue_token()
        invitation = await self._store.create_invitation(
            organization_id=organization_id,
            email=email,
            role=role,
            token_hash=token.digest,
            invited_by=inviter_id,
            expires_at=now + INVITATION_TTL,
            now=now,
        )
        return await self._deliver(invitation, token.raw, inviter_id)

    async def resend(
        self, *, organization_id: int, invitation_id: int, inviter_id: int
    ) -> IssuedInvitation:
        token = issue_token()
        invitation = await self._store.rotate_invitation_token(
            organization_id,
            invitation_id,
            token_hash=token.digest,
            expires_at=self._clock.now() + INVITATION_TTL,
        )
        if invitation is None:
            raise InvitationNotFoundError()
        return await self._deliver(invitation, token.raw, inviter_id)

    async def revoke(self, *, organization_id: int, invitation_id: int) -> None:
        revoked = await self._store.revoke_invitation(
            organization_id, invitation_id, self._clock.now()
        )
        if not revoked:
            raise InvitationNotFoundError()

    async def list_open(self, organization_id: int) -> list[Invitation]:
        return await self._store.list_open_invitations(
            organization_id, self._clock.now()
        )

    # -- invitee actions -----------------------------------------------------

    async def preview(self, token: str) -> InvitationPreview:
        invitation = await self._by_token(token)
        organization = await self._directory.get_organization_summary(
            invitation.organization_id
        )
        inviter = (
            await self._directory.get_user_identity(invitation.invited_by)
            if invitation.invited_by
            else None
        )
        return InvitationPreview(
            organization_name=(organization.name if organization else None)
            or _FALLBACK_ORG_NAME,
            inviter_name=(inviter.name or inviter.email) if inviter else None,
            role=invitation.role,
            email=invitation.email,
            status=invitation.status(self._clock.now()),
        )

    async def require_acceptable(self, token: str, email: str) -> Invitation:
        """Validate ``token`` for ``email`` without consuming it (pre-signup)."""
        invitation = await self._by_token(token)
        if invitation.status(self._clock.now()) is not InvitationStatus.PENDING:
            raise InvitationNotUsableError()
        if invitation.email != email.strip().lower():
            raise InvitationEmailMismatchError()
        return invitation

    async def accept(self, *, token: str, user_id: int, email: str) -> Invitation:
        invitation = await self.require_acceptable(token, email)
        return await self._store.accept_invitation(
            invitation.id,
            user_id=user_id,
            now=self._clock.now(),
            select_organization=True,
        )

    async def has_open_invitation(self, email: str) -> bool:
        return bool(
            await self._store.list_open_invitations_for_email(
                email.strip().lower(), self._clock.now()
            )
        )

    async def claim_pending(
        self, *, user_id: int, verified_email: str, select_latest: bool
    ) -> list[Invitation]:
        """Join every organization that has an open invitation for this address.

        Call only once the address is proven to belong to the user (verified
        signup, verified OAuth email); otherwise anyone could register an
        invited address and take the seat.
        """
        now = self._clock.now()
        open_invitations = await self._store.list_open_invitations_for_email(
            verified_email, now
        )
        claimed: list[Invitation] = []
        for index, invitation in enumerate(open_invitations):
            is_latest = index == len(open_invitations) - 1
            try:
                claimed.append(
                    await self._store.accept_invitation(
                        invitation.id,
                        user_id=user_id,
                        now=now,
                        select_organization=select_latest and is_latest,
                    )
                )
            except InvitationNotUsableError:
                # Revoked or accepted concurrently; nothing to claim.
                continue
        return claimed

    # -- internals -----------------------------------------------------------

    async def _by_token(self, token: str) -> Invitation:
        invitation = await self._store.get_invitation_by_token_hash(hash_token(token))
        if invitation is None:
            raise InvitationNotFoundError()
        return invitation

    def accept_url(self, token: str) -> str:
        return f"{self._app_url}/invite/{token}"

    async def _deliver(
        self, invitation: Invitation, raw_token: str, inviter_id: int
    ) -> IssuedInvitation:
        organization = await self._directory.get_organization_summary(
            invitation.organization_id
        )
        inviter = await self._directory.get_user_identity(inviter_id)
        url = self.accept_url(raw_token)
        message = invitation_email(
            to=invitation.email,
            organization_name=(organization.name if organization else None)
            or _FALLBACK_ORG_NAME,
            inviter_name=(inviter.name or inviter.email) if inviter else None,
            role_label=ROLE_LABELS[invitation.role],
            accept_url=url,
            expires_in_days=INVITATION_TTL.days,
        )
        try:
            await self._email.send(message)
        except EmailDeliveryError:
            logger.exception(f"Failed to email invitation {invitation.id}")
            return IssuedInvitation(invitation, accept_url=url, email_sent=False)
        if not self._email.delivers:
            return IssuedInvitation(invitation, accept_url=url, email_sent=False)
        return IssuedInvitation(invitation, accept_url=None, email_sent=True)
