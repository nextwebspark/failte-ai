"""The login attempt's secrets, kept in a signed HttpOnly cookie.

The cookie binds the provider callback to the browser that started the login
(CSRF / login-fixation protection) without any server-side storage. The PKCE
verifier lives only here, never in a URL.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

STATE_TTL = timedelta(minutes=10)
_AUDIENCE = "dograh-oauth-state"


@dataclass(frozen=True, slots=True)
class OAuthLoginState:
    state: str
    nonce: str
    code_verifier: str
    invite_token: str | None
    next_path: str | None


class OAuthStateCodec:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    def encode(self, value: OAuthLoginState, now: datetime | None = None) -> str:
        issued = now or datetime.now(UTC)
        return jwt.encode(
            {
                "aud": _AUDIENCE,
                "iat": issued,
                "exp": issued + STATE_TTL,
                "state": value.state,
                "nonce": value.nonce,
                "cv": value.code_verifier,
                "inv": value.invite_token,
                "next": value.next_path,
            },
            self._secret,
            algorithm="HS256",
        )

    def decode(self, cookie: str) -> OAuthLoginState | None:
        try:
            claims = jwt.decode(
                cookie, self._secret, algorithms=["HS256"], audience=_AUDIENCE
            )
        except jwt.PyJWTError:
            return None
        return OAuthLoginState(
            state=str(claims["state"]),
            nonce=str(claims["nonce"]),
            code_verifier=str(claims["cv"]),
            invite_token=claims.get("inv"),
            next_path=claims.get("next"),
        )


def states_match(cookie_state: OAuthLoginState, returned_state: str) -> bool:
    return secrets.compare_digest(cookie_state.state, returned_state)


def safe_next_path(value: str | None) -> str | None:
    """Accept only same-origin absolute paths (no open redirects).

    Browsers drop ASCII tab/CR/LF while parsing URLs, so ``/\t/evil.com``
    becomes ``//evil.com``; reject every control character, not just CR/LF.
    """
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(c) < 0x20 or c == "\x7f" for c in value):
        return None
    return value
