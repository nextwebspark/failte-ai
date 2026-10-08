"""FastAPI wiring for ``AccountService`` with production collaborators."""

from typing import Annotated

from fastapi import Depends

from api.constants import ENABLE_SIGNUP, REQUIRE_EMAIL_VERIFICATION, UI_APP_URL
from api.db import db_client
from api.services.auth.accounts import AccountPolicy, AccountService
from api.services.email import EmailSender, get_email_sender
from api.services.invitations import InvitationService, get_invitation_service
from api.services.membership import ensure_user_has_organization
from api.utils.auth import create_jwt_token, hash_password, verify_password
from api.utils.clock import SystemClock


async def _ensure_organization(user_id: int, user_provider_id: str) -> int:
    return await ensure_user_has_organization(
        user_id=user_id, user_provider_id=user_provider_id
    )


def get_account_policy() -> AccountPolicy:
    return AccountPolicy(
        signup_enabled=ENABLE_SIGNUP,
        require_email_verification=REQUIRE_EMAIL_VERIFICATION,
        app_url=UI_APP_URL,
    )


def get_account_service(
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
    invitations: Annotated[InvitationService, Depends(get_invitation_service)],
    policy: Annotated[AccountPolicy, Depends(get_account_policy)],
) -> AccountService:
    return AccountService(
        store=db_client,
        invitations=invitations,
        email_sender=email_sender,
        clock=SystemClock(),
        policy=policy,
        hash_password=hash_password,
        verify_password=verify_password,
        issue_session_token=create_jwt_token,
        ensure_organization=_ensure_organization,
    )
