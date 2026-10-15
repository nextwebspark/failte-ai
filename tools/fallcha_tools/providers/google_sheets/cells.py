"""Pure helpers for sheet cells: A1 ranges, headers, matching, escaping."""

from __future__ import annotations

import re
from collections.abc import Sequence

# Longest cell text returned to the agent; longer cells are cut.
MAX_CELL_CHARS = 500

# A value starting with one of these is a formula in Sheets/Excel/CSV
# viewers. Values are written RAW (never parsed), so the sheet itself never
# evaluates them; the apostrophe also defuses them when the sheet is later
# exported and opened elsewhere (CSV / spreadsheet formula injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# ...except a plain international phone number ("+353 1 234 5678"), the most
# common value a voice agent writes: it cannot call a function or reference
# a cell, so it is kept as typed rather than shown with an apostrophe.
_PHONE_NUMBER = re.compile(r"^\+[0-9][0-9 ().-]{0,30}$")
_SPACES = re.compile(r"\s+")
_UPDATED_ROW = re.compile(r"![A-Z]*([0-9]+)")


def neutralize_formula(value: str) -> str:
    if value.startswith(_FORMULA_PREFIXES) and not _PHONE_NUMBER.fullmatch(value):
        return "'" + value
    return value


def quote_tab(tab: str) -> str:
    """A tab name quoted for A1 notation (handles spaces and quotes)."""
    return "'" + tab.replace("'", "''") + "'"


def rows_range(tab: str, first: int, last: int) -> str:
    """Whole rows ``first``..``last`` of ``tab`` in A1 notation."""
    return f"{quote_tab(tab)}!{first}:{last}"


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def normalize(text: str) -> str:
    """For comparisons: case-folded, whitespace collapsed and trimmed."""
    return _SPACES.sub(" ", text).strip().casefold()


def header_names(row: Sequence[str]) -> list[str]:
    """Column names from a header row. Blank headers are named after their
    column ("Column C"); repeated names get a suffix ("Notes (2)")."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(row):
        name = _SPACES.sub(" ", raw).strip() or f"Column {column_letter(index)}"
        key = name.casefold()
        seen[key] = seen.get(key, 0) + 1
        names.append(name if seen[key] == 1 else f"{name} ({seen[key]})")
    return names


def find_column(headers: Sequence[str], wanted: str) -> int | None:
    target = normalize(wanted)
    for index, name in enumerate(headers):
        if normalize(name) == target:
            return index
    return None


def cell_text(value: str) -> str:
    return value if len(value) <= MAX_CELL_CHARS else value[:MAX_CELL_CHARS] + "..."


def row_dict(headers: Sequence[str], row: Sequence[str]) -> dict[str, str]:
    """Header -> value for one row; missing cells are empty strings."""
    return {
        name: cell_text(row[i]) if i < len(row) else ""
        for i, name in enumerate(headers)
    }


def updated_row_number(updated_range: str) -> int | None:
    """The first row number of an A1 range like ``'Leads'!A12:D12``."""
    found = _UPDATED_ROW.search(updated_range)
    return int(found.group(1)) if found else None
