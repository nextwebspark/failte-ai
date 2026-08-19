"""Google TTS voice catalogue, served from Google rather than Dograh's MPS.

Upstream's /configurations/voices/{provider} proxies to the hosted MPS service,
which knows nothing about Google. So a BYOK Google deployment got a bare "Enter
voice ID" text box instead of a picker — you had to know that
`en-GB-Chirp3-HD-Kore` existed and type it exactly.

This builds the same VoiceInfo shape from Google's own voices API, labelled the
way a person thinks about it ("British female", "Indian male") rather than by
locale code, and synthesises previews on demand because Google publishes no
sample URLs.

Credentials follow the usual chain: the org's configured TTS credentials if it
has any, otherwise Application Default Credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from loguru import logger

VOICES_URL = "https://texttospeech.googleapis.com/v1/voices"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Previews are identical for a given voice, so synthesising one twice is money
# and latency for nothing.
PREVIEW_CACHE = Path("/tmp/dograh-voice-previews")
PREVIEW_TEXT = (
    "Hello, thanks for calling. I can check that for you right now."
)

# Google encodes the model family in the voice name.
MODEL_FAMILIES = [
    "Chirp3-HD", "Chirp-HD", "Journey", "Studio", "Neural2", "Polyglot",
    "Wavenet", "News", "Casual", "Standard",
]

# Maps the model id stored in our config to the token in the voice name.
MODEL_ID_TO_FAMILY = {
    "chirp_3_hd": "Chirp3-HD",
    "chirp_hd": "Chirp-HD",
    "neural2": "Neural2",
    "studio": "Studio",
    "wavenet": "Wavenet",
    "standard": "Standard",
    "journey": "Journey",
    "polyglot": "Polyglot",
}

LANGUAGE_NAMES = {
    "en": "English", "ga": "Irish", "fr": "French", "de": "German",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "pl": "Polish", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "bn": "Bengali", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
    "mr": "Marathi", "pa": "Punjabi", "ur": "Urdu", "ar": "Arabic",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ru": "Russian",
    "tr": "Turkish", "sv": "Swedish", "da": "Danish", "no": "Norwegian",
    "fi": "Finnish", "cs": "Czech", "el": "Greek", "he": "Hebrew",
    "th": "Thai", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay",
    "uk": "Ukrainian", "ro": "Romanian", "hu": "Hungarian", "sk": "Slovak",
}

REGION_NAMES = {
    "US": "American", "GB": "British", "AU": "Australian", "IN": "Indian",
    "IE": "Irish", "CA": "Canadian", "NZ": "New Zealand", "ZA": "South African",
    "SG": "Singaporean", "PH": "Filipino", "NG": "Nigerian", "KE": "Kenyan",
    "ES": "Spain", "MX": "Mexican", "BR": "Brazilian", "PT": "Portugal",
    "FR": "French", "DE": "German", "IT": "Italian", "NL": "Dutch",
}


def _credentials(credentials_json: str | None):
    """Service-account JSON if the org configured one, else ADC."""
    if credentials_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(credentials_json), scopes=SCOPES
        )
    else:
        creds, _ = google_auth_default(scopes=SCOPES)
    creds.refresh(GoogleAuthRequest())
    return creds


def _family(voice_name: str) -> str | None:
    for family in MODEL_FAMILIES:
        if f"-{family}-" in voice_name:
            return family
    return None


def _label(locale: str, gender: str) -> tuple[str, str, str, str]:
    """Turn 'en-GB' + 'FEMALE' into ('en', 'gb', 'female', 'British female').

    The language is the BASE code, not the locale: the picker's language filter
    speaks ISO-639-1 ("en") and its display names are keyed that way, so a voice
    tagged "en-GB" would match neither. The region survives as the accent, which
    is what a caller actually hears, and the full locale is recoverable from the
    voice id when we synthesise a preview.
    """
    parts = locale.split("-")
    lang = parts[0].lower()
    region = parts[1].upper() if len(parts) > 1 else ""

    language_name = LANGUAGE_NAMES.get(lang, lang.upper())
    region_name = REGION_NAMES.get(region, "")
    # Google also returns SSML_VOICE_GENDER_UNSPECIFIED, which is not a word
    # anyone wants to see in a filter dropdown.
    gender_word = gender.lower() if gender in ("MALE", "FEMALE") else "neutral"

    # "British female" reads better than "English (GB) female"; fall back to the
    # language when we have no name for the region.
    descriptor = region_name or language_name
    return lang, region.lower(), gender_word, f"{descriptor} {gender_word}"


async def list_voices(
    *,
    credentials_json: str | None = None,
    model: str | None = None,
    language: str | None = None,
    q: str | None = None,
    gender: str | None = None,
    accent: str | None = None,
) -> dict:
    """Fetch and shape Google's voice catalogue. Same contract as MPS."""
    creds = _credentials(credentials_json)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            VOICES_URL, headers={"Authorization": f"Bearer {creds.token}"}
        )
    if resp.status_code != 200:
        raise RuntimeError(f"google voices api {resp.status_code}: {resp.text[:200]}")

    wanted_family = MODEL_ID_TO_FAMILY.get((model or "").lower())
    voices: list[dict] = []

    for entry in resp.json().get("voices", []):
        name = entry.get("name", "")
        locale = (entry.get("languageCodes") or [""])[0]
        if not name or not locale:
            continue

        family = _family(name)
        if wanted_family and family != wanted_family:
            continue

        lang_code, accent_code, gender_word, human = _label(
            locale, entry.get("ssmlGender", "NEUTRAL")
        )

        voices.append(
            {
                # The picker renders the name over a trait line it builds itself
                # from accent/gender/language, so the name is just "Kore" — the
                # human label here would only repeat what sits under it.
                "voice_id": name,
                "name": name.rsplit("-", 1)[-1],
                "description": f"{human}{f' · {family}' if family else ''}",
                "accent": accent_code,
                "gender": gender_word,
                "language": lang_code,
                "preview_url": f"/api/v1/user/configurations/voices/google/preview?voice_id={name}",
            }
        )

    def matches(v: dict) -> bool:
        if language and v["language"].lower() != language.lower():
            return False
        if gender and v["gender"] != gender.lower():
            return False
        if accent and (v["accent"] or "") != accent.lower():
            return False
        if q and not re.search(re.escape(q), f"{v['voice_id']} {v['name']}", re.I):
            return False
        return True

    filtered = [v for v in voices if matches(v)]
    filtered.sort(key=lambda v: (v["language"], v["gender"], v["voice_id"]))

    # Facets describe the WHOLE catalogue for this model, not the filtered view,
    # so the dropdowns do not collapse to whatever is currently selected.
    return {
        "provider": "google",
        "voices": filtered,
        "facets": {
            "genders": sorted({v["gender"] for v in voices if v["gender"]}),
            "accents": sorted({v["accent"] for v in voices if v["accent"]}),
            "languages": sorted({v["language"] for v in voices if v["language"]}),
        },
    }


async def preview_audio(voice_id: str, *, credentials_json: str | None = None) -> bytes:
    """Synthesise a short sample. Google publishes no preview URLs of its own."""
    if not re.fullmatch(r"[A-Za-z0-9-]{3,64}", voice_id):
        raise ValueError("invalid voice id")

    PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{voice_id}|{PREVIEW_TEXT}".encode()).hexdigest()[:32]
    cached = PREVIEW_CACHE / f"{key}.mp3"
    if cached.exists():
        return cached.read_bytes()

    locale = "-".join(voice_id.split("-")[:2])
    creds = _credentials(credentials_json)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            headers={"Authorization": f"Bearer {creds.token}"},
            json={
                "input": {"text": PREVIEW_TEXT},
                "voice": {"languageCode": locale, "name": voice_id},
                "audioConfig": {"audioEncoding": "MP3"},
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"synthesize {resp.status_code}: {resp.text[:200]}")

    audio = base64.b64decode(resp.json()["audioContent"])
    cached.write_bytes(audio)
    logger.debug(f"cached voice preview {voice_id} ({len(audio)} bytes)")
    return audio
