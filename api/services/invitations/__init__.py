from typing import Annotated

from fastapi import Depends

from api.constants import UI_APP_URL
from api.db import db_client
from api.services.email import EmailSender, get_email_sender
from api.services.invitations.service import (
    InvitationPreview,
    InvitationService,
    IssuedInvitation,
)
from api.utils.clock import SystemClock


def get_invitation_service(
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> InvitationService:
    """FastAPI dependency wiring the service to the real DB and mailer."""
    return InvitationService(
        store=db_client,
        directory=db_client,
        email_sender=email_sender,
        clock=SystemClock(),
        app_url=UI_APP_URL,
    )


__all__ = [
    "InvitationPreview",
    "InvitationService",
    "IssuedInvitation",
    "get_invitation_service",
]
