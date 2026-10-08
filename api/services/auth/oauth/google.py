"""Google Sign-In via OpenID Connect (authorization code + PKCE)."""

import asyncio
from typing import Any
from urllib.parse import urlencode

import aiohttp
import jwt
from pydantic import SecretStr

from api.errors.account import OAuthLoginError
from api.services.auth.oauth.base import AuthorizationRequest, OAuthIdentity

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Shared so Google's signing keys are fetched once and cached.
_jwks_client = jwt.PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=3600)


class GoogleOAuthProvider:
    def __init__(
        self, *, client_id: str, client_secret: SecretStr, redirect_uri: str
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def authorization_url(self, request: AuthorizationRequest) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": request.state,
                "nonce": request.nonce,
                "code_challenge": request.code_challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        return f"{_AUTHORIZE_URL}?{query}"

    async def exchange_code(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> OAuthIdentity:
        id_token = await self._fetch_id_token(code, code_verifier)
        claims = await self._verify_id_token(id_token)
        if claims.get("nonce") != nonce:
            raise OAuthLoginError("Google sign-in could not be verified")
        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise OAuthLoginError("Your Google account has no email address")
        name = claims.get("name")
        picture = claims.get("picture")
        return OAuthIdentity(
            subject=str(claims["sub"]),
            email=email.lower(),
            email_verified=claims.get("email_verified") is True,
            name=name if isinstance(name, str) else None,
            picture=picture if isinstance(picture, str) else None,
        )

    async def _fetch_id_token(self, code: str, code_verifier: str) -> str:
        form = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret.get_secret_value(),
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT) as session,
                session.post(_TOKEN_URL, data=form) as response,
            ):
                payload: dict[str, Any] = await response.json(content_type=None)
                if response.status >= 400 or "id_token" not in payload:
                    raise OAuthLoginError("Google sign-in failed; please try again")
                return str(payload["id_token"])
        except aiohttp.ClientError as exc:
            raise OAuthLoginError("Could not reach Google; please try again") from exc

    async def _verify_id_token(self, id_token: str) -> dict[str, Any]:
        try:
            key = await asyncio.to_thread(
                _jwks_client.get_signing_key_from_jwt, id_token
            )
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=_ISSUERS,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise OAuthLoginError("Google sign-in could not be verified") from exc
        return claims
