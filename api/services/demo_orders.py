"""Sample shop orders for demo workspaces, and the verified order lookup an
agent calls to read one.

A seeded demo workspace (``api/scripts/seed_demo_accounts.py``) can hold a
handful of made-up orders in its ``DEMO_SAMPLE_ORDERS`` configuration row,
with a lookup key. The agent reaches them through an ordinary HTTP tool
(the Tools feature) that calls ``POST /api/v1/demo/sample-orders/lookup``
with that key as a bearer credential: exactly how it would call a shop's own
order API, so going live means pointing the tool at the shop's platform.

The rules live here, not in the prompt:

* an order is only read with its order number plus the email address or the
  mobile number on it, compared normalised (case and spaces in the email;
  +353 / +44 / 0 and spaces in the phone). The caller's name is a soft check
  that never decides on its own;
* a match returns only what answers "where is my order": status, its date,
  an items summary, the courier, the last four characters of the tracking
  number, an expected date and the delivery town. Never the stored email,
  phone or address;
* anything else gets the same "couldn't verify" answer, with no hint of
  which detail was wrong;
* after ``MAX_FAILURES`` failed checks on one call the lookup refuses for the
  rest of it, and the agent offers a callback instead.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import date
from typing import Any

from api.enums import OrganizationConfigurationKey

SAMPLE_ORDERS_KEY = OrganizationConfigurationKey.DEMO_SAMPLE_ORDERS.value
DEMO_ACCOUNT_KEY = OrganizationConfigurationKey.DEMO_ACCOUNT.value
# Failed checks allowed on one call before the lookup stops answering.
MAX_FAILURES = 2
# The lookup key: "lmdemo-orders.<organization id>.<secret>".
KEY_PREFIX = "lmdemo-orders"

NOT_VERIFIED = (
    "I couldn't verify that order with those details. Please check the order "
    "number and the email address or mobile number used on the order."
)
LOCKED = (
    "The order couldn't be verified on this call. Offer to have a member of "
    "the team call the customer back about it; don't try again on this call."
)
NEED_CONTACT = (
    "To look up an order I need the order number and the email address or "
    "mobile number used on the order."
)

STATUS_WORDS = {
    "received": "Received, not yet picked",
    "processing": "Being picked and packed",
    "dispatched": "Dispatched",
    "delivered": "Delivered",
    "awaiting_stock": "Waiting for stock",
    "back_ordered": "Back-ordered",
    "partially_dispatched": "Partly dispatched",
    "return_requested": "Return requested, waiting for authorisation",
    "return_authorised": "Return authorised",
    "refunded": "Refunded",
    "cancelled": "Cancelled",
}


def new_lookup_key(organization_id: int) -> str:
    return f"{KEY_PREFIX}.{organization_id}.{secrets.token_urlsafe(24)}"


def organization_of_key(key: str) -> int | None:
    """The organization a lookup key names, or None if it isn't one."""
    parts = (key or "").strip().split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX or not parts[1].isdigit():
        return None
    return int(parts[1])


def same_key(given: str, stored: str) -> bool:
    return bool(given and stored) and hmac.compare_digest(
        given.strip().encode(), stored.encode()
    )


def bearer(authorization: str | None) -> str:
    value = (authorization or "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


# --- comparing what the caller said with the order -------------------------


def order_key(value: Any) -> str:
    """CHM-104203, "chm 104203" and "104203" all read as CHM104203."""
    text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if text.isdigit():
        text = f"CHM{text}"
    return text


def email_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def phone_key(value: Any) -> str:
    """A phone number in its national form, digits only: +353 85 555 0101,
    00353855550101 and 085 555 0101 all read as 0855550101 (+44 likewise)."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    for country in ("353", "44"):
        if digits.startswith(country) and len(digits) > len(country) + 7:
            rest = digits[len(country) :]
            return rest if rest.startswith("0") else f"0{rest}"
    return digits


def _name_words(value: Any) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", str(value or "").lower()) if len(w) > 1}


@dataclass(frozen=True, slots=True)
class Check:
    verified: bool
    # Why not, for the logs only; never returned to the caller.
    reason: str = ""
    order: dict[str, Any] | None = None
    name_matched: bool | None = None


def check(
    orders: list[dict[str, Any]],
    *,
    order_number: Any,
    email: Any = None,
    phone: Any = None,
    caller_name: Any = None,
) -> Check:
    """Whether the caller's details match one order (see module doc)."""
    number = order_key(order_number)
    given_email = email_key(email)
    given_phone = phone_key(phone)
    if not number or not (given_email or given_phone):
        return Check(False, "missing details")
    order = next(
        (o for o in orders if order_key(o.get("order_number")) == number), None
    )
    if order is None:
        return Check(False, "no such order")
    email_ok = bool(given_email) and given_email == email_key(order.get("email"))
    phone_ok = len(given_phone) >= 7 and given_phone == phone_key(order.get("mobile"))
    if not (email_ok or phone_ok):
        return Check(False, "contact does not match")
    name_matched = None
    if caller_name:
        name_matched = bool(
            _name_words(caller_name) & _name_words(order.get("customer"))
        )
    return Check(True, order=order, name_matched=name_matched)


def _spoken_date(value: str | None) -> str | None:
    if not value:
        return None
    day = date.fromisoformat(value)
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def answer(order: dict[str, Any]) -> dict[str, Any]:
    """What the agent may tell a verified caller, and nothing more."""
    status = str(order.get("status") or "")
    tracking = str(order.get("tracking") or "")
    items = [
        f"{line['quantity']} x {line['name']}"
        + (f" ({line['status']})" if line.get("status") else "")
        for line in order.get("items") or []
    ]
    result: dict[str, Any] = {
        "lookup": "order",
        "verified": True,
        "order_number": order.get("order_number"),
        "status": STATUS_WORDS.get(status, status.replace("_", " ").capitalize()),
        "status_code": status,
        "status_date": order.get("status_date"),
        "status_date_spoken": _spoken_date(order.get("status_date")),
        "items": items,
        "delivery_town": order.get("delivery_town"),
    }
    if order.get("courier"):
        result["courier"] = order["courier"]
    if tracking:
        result["tracking_ending"] = tracking[-4:]
        result["tracking_note"] = (
            "Tracking is in the dispatch email and in the account's Orders page "
            "on chmarine.com."
        )
    if order.get("expected_date"):
        result["expected_date"] = order["expected_date"]
        result["expected_date_spoken"] = _spoken_date(order["expected_date"])
    if order.get("note"):
        result["note"] = order["note"]
    return result


def refusal(*, locked: bool, missing: bool = False) -> dict[str, Any]:
    if locked:
        return {"lookup": "order", "verified": False, "locked": True, "say": LOCKED}
    if missing:
        return {"lookup": "order", "verified": False, "say": NEED_CONTACT}
    return {"lookup": "order", "verified": False, "say": NOT_VERIFIED}


def public_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sample orders as the owner's "Sample orders (demo)" view lists them:
    no email, phone or address, the tracking number shortened."""
    rows = []
    for order in orders:
        tracking = str(order.get("tracking") or "")
        rows.append(
            {
                "order_number": order.get("order_number"),
                "order_date": order.get("order_date"),
                "customer": order.get("customer"),
                "delivery_town": order.get("delivery_town"),
                "items": [
                    f"{line['quantity']} x {line['name']}"
                    for line in order.get("items") or []
                ],
                "total": order.get("total"),
                "status": STATUS_WORDS.get(
                    str(order.get("status") or ""), order.get("status")
                ),
                "status_date": order.get("status_date"),
                "courier": order.get("courier"),
                "tracking_ending": tracking[-4:] if tracking else None,
                # Made-up details a presenter gives on a test call to pass
                # the check (every address is @example.com, every number a
                # 555 or drama-range one).
                "test_email": order.get("email"),
                "test_mobile": order.get("mobile"),
            }
        )
    return rows
