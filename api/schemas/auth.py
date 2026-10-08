from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints

from api.utils.text import reject_control_characters


def _password_min_length(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    return v


NewPassword = Annotated[str, AfterValidator(_password_min_length)]

DisplayName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=100),
    AfterValidator(reject_control_characters),
]


class SignupRequest(BaseModel):
    email: EmailStr
    password: NewPassword
    name: DisplayName | None = None
    # Token from an invitation link: join that organization instead of
    # creating a new one. Allowed even when open signup is disabled.
    invite_token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str | None
    name: str | None = None
    organization_id: int | None = None
    provider_id: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class SignupResponse(BaseModel):
    # Absent when the user must verify their email before logging in.
    token: str | None = None
    user: UserResponse
    verification_required: bool


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenRequest(_Request):
    token: str


class EmailRequest(_Request):
    email: EmailStr


class ResetPasswordRequest(_Request):
    token: str
    password: NewPassword


class GoogleStartResponse(BaseModel):
    authorization_url: str


class GoogleCallbackRequest(_Request):
    code: str
    state: str


class GoogleAuthResponse(AuthResponse):
    # Same-origin path to continue to after login, if one was requested.
    next_path: str | None = None
