"""Deleting a user's own account (GDPR Art. 17)."""

from loguru import logger

from api import constants
from api.db import db_client
from api.db.models import UserModel
from api.errors.privacy import ConfirmationMismatchError, IdentityProviderError
from api.services.auth.stack_auth import StackAuthDeletionError, stackauth

ACCOUNT_WITHOUT_EMAIL_CONFIRMATION = "DELETE"


async def delete_user_account(user: UserModel, *, confirm_email: str) -> None:
    """Delete ``user`` once they have typed their email address (``DELETE``
    for an account without one).

    Refuses while they are the only admin of an organisation with other
    members, or the only member of an organisation (delete that organisation
    first). Their memberships, settings and sign-in tokens go; agents, tools
    and everything else they created stay with their organisations. Under
    Stack Auth the Stack user is deleted inside the same locked transaction,
    after the final check and before the commit, so a Stack failure deletes
    nothing and the user can retry. Afterwards no session of theirs works:
    local session tokens resolve to a user that no longer exists.
    """
    # An account without an email address (some identity-provider accounts)
    # confirms with the word DELETE instead.
    expected = (user.email or "").strip() or ACCOUNT_WITHOUT_EMAIL_CONFIRMATION
    if confirm_email.strip().casefold() != expected.casefold():
        raise ConfirmationMismatchError(
            "Type your email address exactly to confirm the deletion."
        )

    # Fails fast with the reason, before anything else happens; the delete
    # below checks again under the organization locks.
    await db_client.check_user_account_deletable(user.id)

    before_commit = None
    if constants.AUTH_PROVIDER == "stack":

        async def delete_stack_user() -> None:
            # Inside the locked transaction, after the final check: a refusal
            # here rolls the local delete back, and a check that fails never
            # reaches Stack, so nobody is left without a way to sign in.
            try:
                await stackauth.delete_user(user.provider_id)
            except StackAuthDeletionError as exc:
                logger.error(f"Stack Auth refused to delete user {user.id}: {exc}")
                raise IdentityProviderError() from exc

        before_commit = delete_stack_user

    await db_client.delete_user_account(user.id, before_commit=before_commit)
    logger.info(f"User {user.id} deleted their account")
