"""Prices and stock as words (ported from the product service's ``app.py``).

TTS reads bare digits badly over a phone line, so every answer carries a
ready-to-speak sentence the agent reads instead of composing one from raw
fields; that is what stops it inventing prices.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]  # fmt: skip
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]  # fmt: skip
# The original only spoke euro; other currencies get their usual name (or
# the code itself). Euro is invariant in English ("two euro").
_UNITS: dict[str, tuple[str, str]] = {
    "EUR": ("euro", "euro"),
    "GBP": ("pound", "pounds"),
    "USD": ("dollar", "dollars"),
}


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    rest = n % 100
    head = f"{_ONES[n // 100]} hundred"
    return f"{head} and {_under_thousand(rest)}" if rest else head


def number_words(n: int) -> str:
    if n < 1000:
        return _under_thousand(n)
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = f"{_under_thousand(thousands)} thousand"
        if not rest:
            return head
        joiner = " and " if rest < 100 else " "
        return head + joiner + _under_thousand(rest)
    return str(n)


def spoken_price(price: Decimal | None, currency: str | None) -> str:
    if price is None:
        return "price on request"
    code = (currency or "EUR").upper()
    singular, plural = _UNITS.get(code, (code, code))
    cents_total = int((price * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    whole, cents = divmod(cents_total, 100)
    unit = singular if whole == 1 else plural
    words = number_words(whole)
    if cents:
        return f"{words} {unit} {number_words(cents)}"
    return f"{words} {unit}"


def in_stock(availability: str | None) -> bool:
    return (availability or "").lower() == "instock"


def stock_phrase(availability: str | None) -> str:
    return "in stock" if in_stock(availability) else "not in stock at the moment"
