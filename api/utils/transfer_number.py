"""The number an agent puts callers through to ("Pass calls to your team").

Owners type it the way they say it ("087 123 4567"); providers dial E.164
("+353871234567"). This module turns the one into the other, refuses numbers
that can't be called or would loop back to the agent, and knows the reserved
demo numbers that must never be dialled.

SIP destinations (``sip:``/``sips:`` URIs, ``PJSIP/…`` dial strings, bare
``user@host``) are used by PBX setups and are left exactly as typed.

Lives in ``api.utils`` so routes, the transfer resolver and the seed scripts
can import it without pulling in the telephony providers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

try:  # Declared in api/requirements.txt; tolerated missing in an older image.
    import phonenumbers
except ImportError:  # pragma: no cover - exercised only on an old image
    phonenumbers = None

DEFAULT_REGION = "IE"

# The demo accounts' "Pass calls to your team" number (api/scripts/
# seed_demo_accounts.py). It looks like a Dublin landline so it passes the
# number check, which means it could belong to someone: the transfer code
# never dials a number on this list (see ``is_demo_number``).
DEMO_TRANSFER_NUMBER = "+35315550100"
# The placeholder the demo seed used before; still on agents seeded earlier.
LEGACY_DEMO_TRANSFER_NUMBER = "+3530000000"
DEMO_TRANSFER_NUMBERS = frozenset({DEMO_TRANSFER_NUMBER, LEGACY_DEMO_TRANSFER_NUMBER})

# The per-agent "Show the caller's number when we pass a call to you" option,
# kept with the agent's facts (template context variables). Absent means on.
SHOW_CALLER_NUMBER_KEY = "transfer_show_caller_number"
SHOW_CALLER_NUMBER_OFF = "off"

# Providers whose transfer leg can present the original caller's number,
# per their own documentation (``transfer_caller_number_params`` on each):
# Twilio: POST /Calls with From=<caller> and the inbound CallToken.
# Telnyx: POST /calls with from=<caller> and diversion=<our number>.
# Plivo, Cloudonix and Asterisk (ARI) keep the business's number: their
# docs don't say the REST-created leg may present a number we don't own.
CALLER_NUMBER_PROVIDERS = frozenset({"twilio", "telnyx"})

_SIP_DIAL_STRING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*/\S+$")  # PJSIP/101
_FALLBACK_STRIP_RE = re.compile(r"[\s\-\.\(\)]")
_COUNTRY_ADJECTIVE = {"IE": "Irish", "GB": "UK", "US": "US", "CA": "Canadian"}


@dataclass(frozen=True)
class TransferNumberCheck:
    """What the owner typed, checked. ``value`` is what to store and dial."""

    ok: bool
    value: str = ""
    # "+353 87 123 4567" for a phone number; the value itself for SIP.
    display: str = ""
    # "Irish mobile", "UK landline", "Phone system address"…
    kind: str = ""
    error: Optional[str] = None
    is_sip: bool = False
    is_demo: bool = False


def is_sip_destination(raw: str) -> bool:
    """A PBX destination (SIP URI, ``PJSIP/101``, ``101@pbx``), not a number."""
    value = (raw or "").strip()
    lowered = value.lower()
    return (
        lowered.startswith(("sip:", "sips:"))
        or "@" in value
        or bool(_SIP_DIAL_STRING_RE.match(value))
    )


def _fallback_e164(raw: str) -> Optional[str]:
    """Without libphonenumber: strip punctuation, 00 -> +, 0 -> +353."""
    digits = _FALLBACK_STRIP_RE.sub("", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = "+353" + digits[1:]
    elif not digits.startswith("+"):
        return None
    return digits if re.fullmatch(r"\+[1-9]\d{7,14}", digits) else None


def to_e164(raw: str, region: str = DEFAULT_REGION) -> Optional[str]:
    """The E.164 form of a phone number, or None when it can't be read as one.

    Only checks that the number parses; ``check_transfer_number`` also asks
    whether it can be called.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if phonenumbers is None:
        return _fallback_e164(value)
    try:
        parsed = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def dialable_destination(raw: str, region: str = DEFAULT_REGION) -> str:
    """What the transfer dials for a stored destination.

    A number written with spaces, dashes, dots or brackets ("087 123 4567",
    saved before numbers were checked) can't be dialled as it is, so it is
    dialled as E.164 when it reads as a real number. Anything already written
    as one dial string is left exactly as it is: E.164, but also the national
    numbers and short extensions ("101") a PBX dial plan may expect, and SIP
    destinations. So are strings that don't read as a number, for the
    provider to refuse as before.
    """
    value = (raw or "").strip()
    if not value or is_sip_destination(value) or not _FALLBACK_STRIP_RE.search(value):
        return value
    if phonenumbers is None:
        return _fallback_e164(value) or value
    try:
        parsed = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException:
        return value
    if not phonenumbers.is_valid_number(parsed):
        return value
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def is_demo_number(raw: str) -> bool:
    """A reserved demo number, however it was typed."""
    value = (raw or "").strip()
    if not value or is_sip_destination(value):
        return False
    e164 = to_e164(value) or _FALLBACK_STRIP_RE.sub("", value)
    return e164 in DEMO_TRANSFER_NUMBERS


def _kind(parsed) -> str:
    # The country's main region (+44 is the UK, even for a Jersey mobile).
    region = phonenumbers.region_code_for_country_code(parsed.country_code)
    adjective = _COUNTRY_ADJECTIVE.get(region or "")
    number_type = phonenumbers.number_type(parsed)
    types = phonenumbers.PhoneNumberType
    noun = {
        types.MOBILE: "mobile",
        types.FIXED_LINE: "landline",
        types.TOLL_FREE: "freephone number",
        types.VOIP: "internet phone number",
    }.get(number_type, "number")
    if adjective:
        return f"{adjective} {noun}"
    return "International " + ("mobile" if noun == "mobile" else "number")


_TOO_SHORT = (
    "That number is too short. Check the digits, e.g. 087 123 4567 or 01 234 5678."
)
_TOO_LONG = "That number has too many digits. Check it and try again."
_NOT_A_NUMBER = "That doesn't look like a phone number. Type it like 087 123 4567."
_NOT_IN_USE = "That isn't a number that can be called. Check the digits."
_BAD_COUNTRY = (
    "We don't recognise that country code. Start with + and the country code, "
    "e.g. +44 for the UK."
)
_PREMIUM = "Premium-rate numbers can't be used. Use a mobile or landline."
_OWN_NUMBER = (
    "This is the number callers ring. If it forwards to your agent, transfers "
    "go round in a circle. Use a different phone, such as a mobile or a direct "
    "line."
)


def check_transfer_number(
    raw: str,
    *,
    own_numbers: Iterable[str] = (),
    region: str = DEFAULT_REGION,
) -> TransferNumberCheck:
    """Check the number an owner typed for "Pass calls to your team".

    A number without a country code is read as Irish. *own_numbers* are the
    agent's own inbound numbers (E.164): putting a call through to one of
    them would ring the agent again, so they are refused. An empty answer is
    fine (the agent takes a message instead) and comes back as ``ok`` with
    an empty ``value``.
    """
    value = (raw or "").strip()
    if not value:
        return TransferNumberCheck(ok=True)
    if is_sip_destination(value):
        return TransferNumberCheck(
            ok=True,
            value=value,
            display=value,
            kind="Phone system address",
            is_sip=True,
        )
    if not re.search(r"\d", value) or re.search(r"[A-Za-z]", value):
        return TransferNumberCheck(ok=False, error=_NOT_A_NUMBER)

    own = {to_e164(n) or n for n in own_numbers if n}
    if phonenumbers is None:
        e164 = _fallback_e164(value)
        if e164 is None:
            return TransferNumberCheck(ok=False, error=_NOT_A_NUMBER)
        result = TransferNumberCheck(ok=True, value=e164, display=e164, kind="Number")
    else:
        try:
            parsed = phonenumbers.parse(value, region)
        except phonenumbers.NumberParseException as exc:
            reason = exc.error_type
            errors = phonenumbers.NumberParseException
            return TransferNumberCheck(
                ok=False,
                error={
                    errors.INVALID_COUNTRY_CODE: _BAD_COUNTRY,
                    errors.TOO_SHORT_NSN: _TOO_SHORT,
                    errors.TOO_SHORT_AFTER_IDD: _TOO_SHORT,
                    errors.TOO_LONG: _TOO_LONG,
                }.get(reason, _NOT_A_NUMBER),
            )
        possible = phonenumbers.is_possible_number_with_reason(parsed)
        reasons = phonenumbers.ValidationResult
        if possible in (
            reasons.TOO_SHORT,
            reasons.INVALID_LENGTH,
            # Dialled within one area only ("087 123"): too short to put a
            # call through to.
            reasons.IS_POSSIBLE_LOCAL_ONLY,
        ):
            return TransferNumberCheck(ok=False, error=_TOO_SHORT)
        if possible == reasons.TOO_LONG:
            return TransferNumberCheck(ok=False, error=_TOO_LONG)
        if possible == reasons.INVALID_COUNTRY_CODE:
            return TransferNumberCheck(ok=False, error=_BAD_COUNTRY)
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        if not phonenumbers.is_valid_number(parsed):
            return TransferNumberCheck(ok=False, error=_NOT_IN_USE)
        if (
            phonenumbers.number_type(parsed)
            == phonenumbers.PhoneNumberType.PREMIUM_RATE
        ):
            return TransferNumberCheck(ok=False, error=_PREMIUM)
        result = TransferNumberCheck(
            ok=True,
            value=e164,
            display=phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            ),
            kind=_kind(parsed),
        )
    if result.value in own:
        return TransferNumberCheck(ok=False, error=_OWN_NUMBER)
    if result.value in DEMO_TRANSFER_NUMBERS:
        return TransferNumberCheck(
            ok=True,
            value=result.value,
            display=result.display,
            kind=result.kind,
            is_demo=True,
        )
    return result
