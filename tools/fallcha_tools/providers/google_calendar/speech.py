"""Ready-to-speak phrases for the TTS to read verbatim (ported from the shim)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

ORDINALS = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
    20: "twentieth",
    21: "twenty first",
    22: "twenty second",
    23: "twenty third",
    24: "twenty fourth",
    25: "twenty fifth",
    26: "twenty sixth",
    27: "twenty seventh",
    28: "twenty eighth",
    29: "twenty ninth",
    30: "thirtieth",
    31: "thirty first",
}
HOUR_WORDS = {
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "one",
    14: "two",
    15: "three",
    16: "four",
    17: "five",
}
MINUTE_WORDS = {15: "fifteen", 30: "thirty", 45: "forty five"}
NOTHING_FREE = "I have nothing free in that window."


def say_time(slot: datetime) -> str:
    """'Monday the twelfth at nine thirty in the morning'."""
    hour_word = HOUR_WORDS.get(slot.hour, str(((slot.hour - 1) % 12) + 1))
    if slot.minute == 0:
        clock = hour_word
    else:
        clock = f"{hour_word} {MINUTE_WORDS.get(slot.minute, f'{slot.minute:02d}')}"
    part = "in the morning" if slot.hour < 12 else "in the afternoon"
    day = ORDINALS.get(slot.day, str(slot.day))
    return f"{slot.strftime('%A')} the {day} at {clock} {part}"


def join_spoken(slots: Sequence[datetime]) -> str:
    phrases = [say_time(slot) for slot in slots]
    if not phrases:
        return NOTHING_FREE
    if len(phrases) == 1:
        return f"I have {phrases[0]}."
    return f"I have {', '.join(phrases[:-1])}, or {phrases[-1]}."
