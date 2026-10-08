"""Data access for login identities and single-use account tokens."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import UserModel, UserTokenModel
from api.enums import TokenPurpose
from api.errors.account import InvalidAccountTokenError


@dataclass(frozen=True, slots=True)
class AuthAccount:
    user_id: int
    provider_id: str
    email: str | None
    name: str | None
    password_hash: str | None
    email_verified_at: datetime | None
    google_sub: str | None
    selected_organization_id: int | None

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


def _to_account(user: UserModel) -> AuthAccount:
    return AuthAccount(
        user_id=user.id,
        provider_id=user.provider_id,
        email=user.email,
        name=user.name,
        password_hash=user.password_hash,
        email_verified_at=user.email_verified_at,
        google_sub=user.google_sub,
        selected_organization_id=user.selected_organization_id,
    )


def _local_provider_id() -> str:
    return f"oss_{uuid.uuid4().hex}"


class AccountClient(BaseDBClient):
    async def get_account(self, user_id: int) -> AuthAccount | None:
        async with self.async_session() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.id == user_id)
            )
            return _to_account(user) if user else None

    async def get_account_by_email(self, email: str) -> AuthAccount | None:
        async with self.async_session() as session:
            user = await session.scalar(
                select(UserModel).where(func.lower(UserModel.email) == email.lower())
            )
            return _to_account(user) if user else None

    async def get_account_by_google_sub(self, google_sub: str) -> AuthAccount | None:
        async with self.async_session() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.google_sub == google_sub)
            )
            return _to_account(user) if user else None

    async def create_account(
        self,
        *,
        email: str,
        name: str | None,
        password_hash: str | None,
        email_verified_at: datetime | None,
        google_sub: str | None = None,
        avatar_url: str | None = None,
    ) -> AuthAccount:
        async with self.async_session() as session:
            user = UserModel(
                provider_id=_local_provider_id(),
                email=email.lower(),
                name=name,
                password_hash=password_hash,
                email_verified_at=email_verified_at,
                google_sub=google_sub,
                avatar_url=avatar_url,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return _to_account(user)

    async def link_google_account(
        self,
        user_id: int,
        *,
        google_sub: str,
        avatar_url: str | None,
        verified_at: datetime,
        revoke_credentials: bool,
    ) -> AuthAccount:
        """Attach a Google identity; a verified Google email also verifies
        the account's email.

        With ``revoke_credentials`` the password is cleared and every unused
        verification/reset token invalidated, in the same transaction.
        """
        async with self.async_session() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.id == user_id)
            )
            if user is None:
                raise LookupError(f"user {user_id} not found")
            if revoke_credentials:
                user.password_hash = None
                await session.execute(
                    update(UserTokenModel)
                    .where(
                        UserTokenModel.user_id == user_id,
                        UserTokenModel.used_at.is_(None),
                    )
                    .values(used_at=verified_at)
                )
            user.google_sub = google_sub
            if avatar_url and not user.avatar_url:
                user.avatar_url = avatar_url
            if user.email_verified_at is None:
                user.email_verified_at = verified_at
            await session.commit()
            await session.refresh(user)
            return _to_account(user)

    async def mark_email_verified(self, user_id: int, verified_at: datetime) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(UserModel)
                .where(UserModel.id == user_id, UserModel.email_verified_at.is_(None))
                .values(email_verified_at=verified_at)
            )
            await session.commit()

    async def set_password_hash(self, user_id: int, password_hash: str) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(password_hash=password_hash)
            )
            await session.commit()

    async def issue_user_token(
        self,
        *,
        user_id: int,
        purpose: TokenPurpose,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        """Store a new token, invalidating the user's earlier unused tokens
        for the same purpose."""
        async with self.async_session() as session:
            await session.execute(
                update(UserTokenModel)
                .where(
                    UserTokenModel.user_id == user_id,
                    UserTokenModel.purpose == purpose.value,
                    UserTokenModel.used_at.is_(None),
                )
                .values(used_at=now)
            )
            session.add(
                UserTokenModel(
                    user_id=user_id,
                    purpose=purpose.value,
                    token_hash=token_hash,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            await session.commit()

    async def consume_user_token(
        self, *, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> int:
        """Mark a token used and return its user id.

        Raises:
            InvalidAccountTokenError: unknown, wrong purpose, used, or expired.
        """
        async with self.async_session() as session:
            token = await session.scalar(
                select(UserTokenModel)
                .where(
                    UserTokenModel.token_hash == token_hash,
                    UserTokenModel.purpose == purpose.value,
                )
                .with_for_update()
            )
            if token is None or token.used_at is not None or token.expires_at <= now:
                raise InvalidAccountTokenError()
            token.used_at = now
            user_id = token.user_id
            await session.commit()
            return user_id
