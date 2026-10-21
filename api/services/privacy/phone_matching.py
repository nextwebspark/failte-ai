"""Deciding whether a stored address is a data subject's phone number.

Call context stores numbers as the telephony provider sent them: E.164
(``+353871234567``), without the plus (``353871234567``), with an
international ``00`` prefix, in national format with a trunk ``0``
(``0871234567``, as Exotel sends Indian numbers), or as a SIP URI whose user
part is the number. ``normalize_telephony_address`` alone turns national
formats into nonsense (``+0871234567``), so this module compares numbers by
country code and national number instead.

A national-format value carries no country. It is read in the organization's
"home" countries (the countries of its own phone numbers, or the subject's
own country when it has none), so a national number from one country never
matches a subject from another.
"""

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from api.db.privacy_client import NumberPrefilter
from api.utils.telephony_address import normalize_telephony_address
from api.utils.telephony_helper import get_country_code


def _expand(*codes: object) -> frozenset[str]:
    out: set[str] = set()
    for code in codes:
        if isinstance(code, range):
            out.update(str(value) for value in code)
        else:
            out.add(str(code))
    return frozenset(out)


# ITU-T E.164 country calling codes (assigned and reserved). The set is
# prefix-free, so the first match on a number's leading digits is its code.
CALLING_CODES = _expand(
    1,
    7,
    20,
    27,
    *range(30, 35),
    36,
    39,
    40,
    41,
    *range(43, 50),
    *range(51, 59),
    *range(60, 67),
    81,
    82,
    84,
    86,
    *range(90, 96),
    98,
    211,
    212,
    213,
    216,
    218,
    range(220, 270),
    290,
    291,
    *range(297, 300),
    range(350, 360),
    range(370, 390),
    420,
    421,
    423,
    range(500, 510),
    range(590, 600),
    range(670, 700),
    800,
    808,
    850,
    852,
    853,
    855,
    856,
    870,
    878,
    *range(880, 884),
    886,
    888,
    range(960, 980),
    range(990, 1000),
)

# Characters people and providers put inside a phone number.
_SEPARATORS = re.compile(r"[\s\-\(\)\./]")
_DIGITS = re.compile(r"\d+")
# Shortest national number a match on national digits alone is trusted for.
_MIN_NATIONAL_DIGITS = 6
PREFILTER_DIGITS = 7

Reading = Literal["international", "national", "bare"]


class InvalidSubjectNumberError(ValueError):
    pass


def calling_code_of(digits: str) -> Optional[str]:
    for length in (1, 2, 3):
        if digits[:length] in CALLING_CODES:
            return digits[:length]
    return None


def _pstn_reading(text: str) -> Optional[tuple[Reading, str]]:
    """How a plain (non-SIP) value reads as a phone number, if it does.

    ``international``: digits with country code (``+353...``, ``00353...``).
    ``national``: digits after a trunk ``0`` prefix, which is kept (``087...``).
    ``bare``: only digits, either international without ``+`` or national.
    """
    cleaned = _SEPARATORS.sub("", text.strip())
    if cleaned.startswith("+"):
        rest = cleaned[1:]
        if rest.startswith("00"):
            rest = rest[2:]
        elif rest.startswith("0"):
            # "+0..." is a national number someone prefixed with "+".
            return ("national", rest) if _DIGITS.fullmatch(rest) else None
        return ("international", rest) if _DIGITS.fullmatch(rest) else None
    if cleaned.startswith("00"):
        rest = cleaned[2:]
        return ("international", rest) if _DIGITS.fullmatch(rest) else None
    if not _DIGITS.fullmatch(cleaned or "x"):
        return None
    if cleaned.startswith("0"):
        return ("national", cleaned)
    return ("bare", cleaned)


@dataclass(frozen=True)
class StoredAddress:
    pstn: Optional[tuple[Reading, str]] = None
    sip: Optional[str] = None
    other: Optional[str] = None


def _sip_user(value: str) -> Optional[str]:
    rest = value.strip().split(":", 1)[1]
    user, at, _host = rest.partition("@")
    return user.split(";", 1)[0] if at else None


def read_address(value: object) -> StoredAddress:
    if not isinstance(value, str) or not value.strip():
        return StoredAddress()
    text = value.strip()
    if text.lower().startswith(("sip:", "sips:")):
        user = _sip_user(text)
        return StoredAddress(
            pstn=_pstn_reading(user) if user else None,
            sip=normalize_telephony_address(text).canonical,
        )
    pstn = _pstn_reading(text)
    if pstn is not None:
        return StoredAddress(pstn=pstn)
    try:
        return StoredAddress(other=normalize_telephony_address(text).canonical)
    except ValueError:
        return StoredAddress()


@dataclass(frozen=True)
class SubjectNumber:
    """The number a data subject request is about."""

    canonical: str
    prefilter: NumberPrefilter
    # A phone number: its country code (when known) and national number.
    calling_code: Optional[str] = None
    national: Optional[str] = None
    sip: Optional[str] = None
    other: Optional[str] = None
    home_calling_codes: frozenset[str] = frozenset()

    @property
    def international(self) -> Optional[str]:
        if self.national is None:
            return None
        return (self.calling_code or "") + self.national

    def matches(self, value: object) -> bool:
        stored = read_address(value)
        if self.sip and stored.sip == self.sip:
            return True
        if self.other and stored.other == self.other:
            return True
        if stored.pstn is None or self.national is None:
            return False
        reading, digits = stored.pstn
        if reading in ("international", "bare") and digits == self.international:
            return True
        if (
            reading in ("national", "bare")
            and self.calling_code in self.home_calling_codes
            and len(self.national) >= _MIN_NATIONAL_DIGITS
        ):
            # A trunk "0" is not part of the national number, except in
            # countries (Italy) that keep it after the country code too.
            candidates = {digits}
            if reading == "national":
                candidates.add(digits[1:])
            return self.national in candidates
        return False


def home_calling_codes(
    addresses: Iterable[tuple[Optional[str], Optional[str]]],
) -> frozenset[str]:
    """Country codes of the organization's own numbers.

    ``addresses`` are ``(normalized address, ISO country)`` pairs.
    """
    codes: set[str] = set()
    for address, country in addresses:
        if country and get_country_code(country):
            codes.add(get_country_code(country))
        if address:
            reading = _pstn_reading(address)
            if reading and reading[0] == "international":
                code = calling_code_of(reading[1])
                if code:
                    codes.add(code)
    return frozenset(codes)


def _phone_subject(
    reading: tuple[Reading, str], home: frozenset[str]
) -> Optional[tuple[Optional[str], str]]:
    """``(country code, national number)`` of a number typed by a user."""
    kind, digits = reading
    if kind == "national":
        if len(home) != 1:
            raise InvalidSubjectNumberError(
                "Enter the number in international format, starting with + "
                "and the country code."
            )
        return next(iter(home)), digits[1:]
    if kind == "bare" and not 8 <= len(digits) <= 15:
        return None  # an extension, not a phone number
    if not 8 <= len(digits) <= 15:
        raise InvalidSubjectNumberError("That is not a valid phone number.")
    code = calling_code_of(digits)
    if code is None:
        return None, digits
    return code, digits[len(code) :]


def parse_subject_number(
    raw: str, home: frozenset[str] = frozenset(), *, max_length: int = 255
) -> SubjectNumber:
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidSubjectNumberError("Enter a phone number.")
    if len(raw) > max_length:
        raise InvalidSubjectNumberError("That number is too long.")
    stored = read_address(raw)
    phone = _phone_subject(stored.pstn, home) if stored.pstn else None

    if phone is not None:
        code, national = phone
        if len(national) < _MIN_NATIONAL_DIGITS:
            raise InvalidSubjectNumberError("That number is too short to search for.")
        international = (code or "") + national
        return SubjectNumber(
            canonical=f"+{international}",
            prefilter=NumberPrefilter(digits=international[-PREFILTER_DIGITS:]),
            calling_code=code,
            national=national,
            sip=stored.sip,
            home_calling_codes=home or (frozenset({code}) if code else frozenset()),
        )

    if stored.sip:
        rest = stored.sip.split(":", 1)[1]
        user, _, host = rest.partition("@")
        fragment = user if host else rest
        canonical, sip, other = stored.sip, stored.sip, None
    else:
        canonical = normalize_telephony_address(raw).canonical
        fragment, sip, other = canonical, None, canonical
    if len(fragment.strip()) < 3:
        raise InvalidSubjectNumberError("That number is too short to search for.")
    return SubjectNumber(
        canonical=canonical,
        prefilter=NumberPrefilter(fragment=fragment),
        sip=sip,
        other=other,
        home_calling_codes=home,
    )
