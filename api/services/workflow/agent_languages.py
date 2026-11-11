"""The languages an agent speaks: an owner setting kept as a business fact.

English is always on. The owner can add the languages below on "What your
agent knows"; the prompts read the fact as
``{{initial_context.agent_languages | fallback:English}}``, so an agent made
before the setting existed, or one whose owner never touched it, speaks
English only.

The fact is stored as the languages' English names, comma-separated, English
first ("English, Polish"): the prompt reads it as it is, and so does the owner.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

AGENT_LANGUAGES_KEY: Final = "agent_languages"
DEFAULT_LANGUAGE: Final = "en"

# (ISO 639-1 code, English name), in the order the setting offers them.
LANGUAGES: Final[tuple[tuple[str, str], ...]] = (
    ("en", "English"),
    ("ga", "Irish"),
    ("pl", "Polish"),
    ("lt", "Lithuanian"),
    ("ro", "Romanian"),
    ("pt", "Portuguese"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("uk", "Ukrainian"),
    ("zh", "Chinese"),
    ("ar", "Arabic"),
)
_NAME_BY_CODE: Final = dict(LANGUAGES)
_CODE_BY_NAME: Final = {name.casefold(): code for code, name in LANGUAGES}
_ORDER: Final = [code for code, _ in LANGUAGES]

# Names a reviewer might use for a language we don't offer; only for display.
_OTHER_NAMES: Final = {
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "ru": "Russian",
    "lv": "Latvian",
    "hu": "Hungarian",
    "cs": "Czech",
    "sk": "Slovak",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "tr": "Turkish",
    "hi": "Hindi",
    "ur": "Urdu",
    "bn": "Bengali",
    "pa": "Punjabi",
    "ta": "Tamil",
    "tl": "Tagalog",
    "vi": "Vietnamese",
    "ja": "Japanese",
    "ko": "Korean",
    "fa": "Persian",
    "so": "Somali",
    "sw": "Swahili",
    "yo": "Yoruba",
    "sq": "Albanian",
    "ka": "Georgian",
    "el": "Greek",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "he": "Hebrew",
}


class AgentLanguagesError(ValueError):
    pass


def language_code(value: str) -> str | None:
    """The code for an offered language, given its code or English name."""
    token = value.strip().casefold()
    if token in _NAME_BY_CODE:
        return token
    return _CODE_BY_NAME.get(token)


def language_name(code: str | None) -> str | None:
    """The English name for an ISO 639-1 code (offered or not), or None."""
    if not code:
        return None
    base = code.strip().lower().split("-")[0].split("_")[0]
    return _NAME_BY_CODE.get(base) or _OTHER_NAMES.get(base)


def _codes(values: Iterable[str]) -> list[str]:
    chosen = {DEFAULT_LANGUAGE}
    for value in values:
        if not value.strip():
            continue
        code = language_code(value)
        if code is None:
            raise AgentLanguagesError(
                f"{value.strip()!r} isn't one of the languages your agent can speak."
            )
        chosen.add(code)
    return [code for code in _ORDER if code in chosen]


def agent_language_codes(fact: str | None) -> list[str]:
    """The codes an agent speaks, from its stored fact; ["en"] when unset.
    Unknown entries in a stored value are ignored rather than raised."""
    codes = {DEFAULT_LANGUAGE}
    for part in (fact or "").split(","):
        code = language_code(part)
        if code is not None:
            codes.add(code)
    return [code for code in _ORDER if code in codes]


def normalised_agent_languages(value: str | None) -> str | None:
    """The fact as it is stored: names, English first, comma-separated. Accepts
    codes or names. Returns None for English only (the prompt's fallback says
    English), so an untouched agent stores nothing. Raises
    AgentLanguagesError for a language that isn't offered."""
    codes = _codes((value or "").split(","))
    if codes == [DEFAULT_LANGUAGE]:
        return None
    return ", ".join(_NAME_BY_CODE[code] for code in codes)


def speaks(fact: str | None, code: str | None) -> bool:
    """Whether an agent with this fact speaks the language *code*."""
    if not code:
        return True
    base = code.strip().lower().split("-")[0].split("_")[0]
    return base in agent_language_codes(fact)
