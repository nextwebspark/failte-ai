from types import TracebackType
from typing import Any, ClassVar, Self
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from api.services.email.base import EmailDeliveryError, EmailMessage
from api.services.email.resend_sender import ResendEmailSender

_MESSAGE = EmailMessage(
    to="owner@example.com", subject="Hi", text="Hello", html="<p>Hello</p>"
)


class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class _FakeSession:
    """Stands in for aiohttp.ClientSession and records the last request."""

    response: ClassVar[_FakeResponse] = _FakeResponse(200, "{}")
    last_request: ClassVar[dict[str, Any]] = {}

    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        _FakeSession.last_request = {"url": url, **kwargs}
        return _FakeSession.response


def _sender() -> ResendEmailSender:
    return ResendEmailSender(SecretStr("re_test"), "Failte AI <onboarding@resend.dev>")


async def test_send_posts_message_with_bearer_key() -> None:
    _FakeSession.response = _FakeResponse(200, '{"id": "abc"}')
    with patch("api.services.email.resend_sender.aiohttp.ClientSession", _FakeSession):
        await _sender().send(_MESSAGE)

    request = _FakeSession.last_request
    assert request["headers"] == {"Authorization": "Bearer re_test"}
    assert request["json"]["to"] == ["owner@example.com"]
    assert request["json"]["from"] == "Failte AI <onboarding@resend.dev>"


async def test_rejection_includes_resend_explanation() -> None:
    body = (
        '{"statusCode":403,"name":"validation_error","message":"You can only '
        'send testing emails to your own email address"}'
    )
    _FakeSession.response = _FakeResponse(403, body)
    with (
        patch("api.services.email.resend_sender.aiohttp.ClientSession", _FakeSession),
        pytest.raises(EmailDeliveryError) as excinfo,
    ):
        await _sender().send(_MESSAGE)

    assert "HTTP 403" in str(excinfo.value)
    assert "only send testing emails to your own email address" in str(excinfo.value)


async def test_rejection_detail_is_truncated() -> None:
    _FakeSession.response = _FakeResponse(500, "x" * 5000)
    with (
        patch("api.services.email.resend_sender.aiohttp.ClientSession", _FakeSession),
        pytest.raises(EmailDeliveryError) as excinfo,
    ):
        await _sender().send(_MESSAGE)

    assert len(str(excinfo.value)) < 400
