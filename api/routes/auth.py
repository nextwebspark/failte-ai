import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from api.constants import OSS_JWT_SECRET
from api.db.account_client import AuthAccount
from api.db.models import UserModel
from api.enums import PostHogEvent
from api.errors.account import OAuthLoginError
from api.schemas.auth import (
    AuthResponse,
    EmailRequest,
    GoogleAuthResponse,
    GoogleCallbackRequest,
    GoogleStartResponse,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    TokenRequest,
    UserResponse,
)
from api.services.auth.account_dependencies import get_account_service
from api.services.auth.accounts import AccountService, PasswordCredentials, Session
from api.services.auth.depends import get_user, require_local_auth
from api.services.auth.oauth import (
    AuthorizationRequest,
    OAuthProvider,
    get_google_oauth_provider,
)
from api.services.auth.oauth.pkce import code_challenge_s256, new_code_verifier
from api.services.auth.oauth.state import (
    STATE_TTL,
    OAuthLoginState,
    OAuthStateCodec,
    safe_next_path,
    states_match,
)
from api.services.posthog_client import capture_event

router = APIRouter(prefix="/auth", tags=["auth"])

# Email/password and Google sign-in exist only with AUTH_PROVIDER=local; the
# routes stay mounted so the OpenAPI spec doesn't vary by deployment.
LOCAL_ONLY = [Depends(require_local_auth)]

Accounts = Annotated[AccountService, Depends(get_account_service)]

_OAUTH_COOKIE = "dograh_oauth_state"
_OAUTH_COOKIE_PATH = "/api/v1/auth/google"
_state_codec = OAuthStateCodec(OSS_JWT_SECRET)


def _user_response(account: AuthAccount, organization_id: int | None) -> UserResponse:
    return UserResponse(
        id=account.user_id,
        email=account.email,
        name=account.name,
        organization_id=organization_id,
        provider_id=account.provider_id,
    )


def _auth_response(session: Session) -> AuthResponse:
    return AuthResponse(
        token=session.token,
        user=_user_response(session.account, session.organization_id),
    )


def _track(event: PostHogEvent, session_or_account: Session | AuthAccount) -> None:
    if isinstance(session_or_account, Session):
        account, organization_id = (
            session_or_account.account,
            session_or_account.organization_id,
        )
    else:
        account, organization_id = session_or_account, None
    capture_event(
        distinct_id=account.provider_id,
        event=event,
        properties={"organization_id": organization_id, "auth_provider": "local"},
    )


# -- password accounts --------------------------------------------------------


@router.post("/signup", response_model=SignupResponse, dependencies=LOCAL_ONLY)
async def signup(request: SignupRequest, accounts: Accounts) -> SignupResponse:
    outcome = await accounts.signup(
        PasswordCredentials(email=request.email, password=request.password),
        name=request.name,
        invite_token=request.invite_token,
    )
    _track(PostHogEvent.SIGNED_UP, outcome.session or outcome.account)
    if outcome.session is None:
        return SignupResponse(
            user=_user_response(outcome.account, None), verification_required=True
        )
    return SignupResponse(
        token=outcome.session.token,
        user=_user_response(outcome.account, outcome.session.organization_id),
        verification_required=False,
    )


@router.post("/login", response_model=AuthResponse, dependencies=LOCAL_ONLY)
async def login(request: LoginRequest, accounts: Accounts) -> AuthResponse:
    session = await accounts.login(
        PasswordCredentials(email=request.email, password=request.password)
    )
    _track(PostHogEvent.SIGNED_IN, session)
    return _auth_response(session)


@router.post("/verify-email", response_model=AuthResponse, dependencies=LOCAL_ONLY)
async def verify_email(request: TokenRequest, accounts: Accounts) -> AuthResponse:
    return _auth_response(await accounts.verify_email(request.token))


@router.post("/resend-verification", status_code=202, dependencies=LOCAL_ONLY)
async def resend_verification(request: EmailRequest, accounts: Accounts) -> Response:
    await accounts.resend_verification(request.email)
    return Response(status_code=202)


@router.post("/forgot-password", status_code=202, dependencies=LOCAL_ONLY)
async def forgot_password(request: EmailRequest, accounts: Accounts) -> Response:
    await accounts.request_password_reset(request.email)
    return Response(status_code=202)


@router.post("/reset-password", response_model=AuthResponse, dependencies=LOCAL_ONLY)
async def reset_password(
    request: ResetPasswordRequest, accounts: Accounts
) -> AuthResponse:
    return _auth_response(
        await accounts.reset_password(request.token, request.password)
    )


# -- Google ---------------------------------------------------------------------


def _require_google(
    provider: Annotated[OAuthProvider | None, Depends(get_google_oauth_provider)],
) -> OAuthProvider:
    if provider is None:
        raise HTTPException(status_code=404, detail="Google sign-in is not enabled")
    return provider


Google = Annotated[OAuthProvider, Depends(_require_google)]


@router.get(
    "/google/start", response_model=GoogleStartResponse, dependencies=LOCAL_ONLY
)
async def google_start(
    request: Request,
    response: Response,
    google: Google,
    invite_token: str | None = None,
    next: str | None = None,
) -> GoogleStartResponse:
    """Begin Google sign-in. The browser should navigate to the returned URL.

    Returns JSON rather than a redirect because the UI reaches the API
    through a proxy that follows redirects server-side.
    """
    login_state = OAuthLoginState(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=new_code_verifier(),
        invite_token=invite_token,
        next_path=safe_next_path(next),
    )
    response.set_cookie(
        _OAUTH_COOKIE,
        _state_codec.encode(login_state),
        max_age=int(STATE_TTL.total_seconds()),
        path=_OAUTH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
    url = google.authorization_url(
        AuthorizationRequest(
            state=login_state.state,
            nonce=login_state.nonce,
            code_challenge=code_challenge_s256(login_state.code_verifier),
        )
    )
    return GoogleStartResponse(authorization_url=url)


@router.post(
    "/google/callback", response_model=GoogleAuthResponse, dependencies=LOCAL_ONLY
)
async def google_callback(
    request: GoogleCallbackRequest,
    response: Response,
    google: Google,
    accounts: Accounts,
    oauth_cookie: Annotated[str | None, Cookie(alias=_OAUTH_COOKIE)] = None,
) -> GoogleAuthResponse:
    """Finish Google sign-in with the ``code``/``state`` Google returned."""
    response.delete_cookie(_OAUTH_COOKIE, path=_OAUTH_COOKIE_PATH)
    login_state = _state_codec.decode(oauth_cookie) if oauth_cookie else None
    if login_state is None or not states_match(login_state, request.state):
        raise OAuthLoginError("Sign-in expired or was started elsewhere; try again")

    identity = await google.exchange_code(
        code=request.code,
        code_verifier=login_state.code_verifier,
        nonce=login_state.nonce,
    )
    session = await accounts.login_with_google(
        identity, invite_token=login_state.invite_token
    )
    _track(PostHogEvent.SIGNED_IN, session)
    return GoogleAuthResponse(
        token=session.token,
        user=_user_response(session.account, session.organization_id),
        next_path=login_state.next_path,
    )


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",")[0].strip() == "https"


# -- current user ---------------------------------------------------------------


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user: Annotated[UserModel, Depends(get_user)],
) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        organization_id=user.selected_organization_id,
        provider_id=user.provider_id,
    )
