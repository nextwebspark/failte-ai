"""Helpers for user-supplied display text (names) that ends up in headers,
emails and the UI."""

import re

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def has_control_characters(value: str) -> bool:
    return bool(_CONTROL_CHARACTERS.search(value))


def strip_control_characters(value: str) -> str:
    """Replace control characters (CR/LF/TAB, ...) with spaces and collapse
    the result, e.g. for an email header built from user text."""
    return " ".join(_CONTROL_CHARACTERS.sub(" ", value).split())


def reject_control_characters(value: str) -> str:
    """Pydantic validator: names must be single-line printable text."""
    if has_control_characters(value):
        raise ValueError("must not contain control characters or line breaks")
    return value
