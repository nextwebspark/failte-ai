import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models import OrganizationModel
from api.routes.billing_webhooks import router
from api.services.billing import stripe_client, webhooks

WEBHOOK_SECRET = "whsec_test_secret"


def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _signed(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def _event_payload(event_type: str) -> bytes:
    return json.dumps(
        {
            "id": f"evt_{uuid.uuid4().hex}",
            "object": "event",
            "type": event_type,
            "data": {"object": {"id": "cs_test_123", "object": "checkout.session"}},
        }
    ).encode()


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(stripe_client, "STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)


def test_webhook_rejects_invalid_signature(webhook_secret):
    client = TestClient(_make_test_app())
    payload = _event_payload("checkout.session.completed")

    response = client.post(
        "/billing/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": _signed(payload, secret="whsec_wrong")},
    )

    assert response.status_code == 400


def test_webhook_rejects_missing_signature(webhook_secret):
    client = TestClient(_make_test_app())

    response = client.post(
        "/billing/stripe/webhook",
        content=_event_payload("checkout.session.completed"),
    )

    assert response.status_code == 400


def test_webhook_dispatches_verified_event(webhook_secret, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setitem(webhooks._HANDLERS, "checkout.session.completed", handler)
    client = TestClient(_make_test_app())
    payload = _event_payload("checkout.session.completed")

    response = client.post(
        "/billing/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": _signed(payload)},
    )

    assert response.status_code == 200
    handler.assert_awaited_once()
    assert handler.await_args.args[0].type == "checkout.session.completed"


def test_webhook_acknowledges_unhandled_event(webhook_secret):
    client = TestClient(_make_test_app())
    payload = _event_payload("customer.created")

    response = client.post(
        "/billing/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": _signed(payload)},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ensure_stripe_customer_creates_once(
    db_session, async_session, monkeypatch
):
    organization = OrganizationModel(provider_id=f"stripe-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()

    create = AsyncMock(return_value=SimpleNamespace(id="cus_test_1"))
    fake_client = MagicMock()
    fake_client.v1.customers.create_async = create
    monkeypatch.setattr(stripe_client, "get_stripe_client", lambda: fake_client)

    first = await stripe_client.ensure_stripe_customer(
        organization.id, email="owner@example.com"
    )
    second = await stripe_client.ensure_stripe_customer(organization.id)

    assert first == second == "cus_test_1"
    create.assert_awaited_once()
    params = create.await_args.kwargs["params"]
    assert params["metadata"] == {"organization_id": str(organization.id)}
    assert params["email"] == "owner@example.com"
