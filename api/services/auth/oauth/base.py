"""Provider-agnostic OAuth / OpenID Connect contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OAuthIdentity:
    """A user identity asserted by the provider's verified ID token."""

    subject: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    state: str
    nonce: str
    code_challenge: str


class OAuthProvider(Protocol):
    def authorization_url(self, request: AuthorizationRequest) -> str: ...

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> OAuthIdentity:
        """Redeem the authorization code; raise ``OAuthLoginError`` on failure."""
        ...
