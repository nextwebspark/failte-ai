"""Estimated model-provider cost of a call, for margin monitoring.

Customers are billed per minute, never by tokens; this only tells us what a
call cost us so the per-minute rate can be tuned. Estimates use list prices
and ignore context-cache discounts, so they err on the high side.

Keep the table in step with Google's published pricing
(https://ai.google.dev/gemini-api/docs/pricing). Google bills in USD.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Convert USD provider prices to EUR. Update from time to time.
USD_TO_EUR = Decimal("0.92")

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class TokenPrices:
    """USD per million tokens."""

    text_input: Decimal
    audio_input: Decimal
    text_output: Decimal
    audio_output: Decimal


# First match wins, so list more specific model-name fragments first.
MODEL_PRICES_USD: tuple[tuple[str, TokenPrices], ...] = (
    # Gemini Live native audio (speech-to-speech).
    (
        "native-audio",
        TokenPrices(
            text_input=Decimal("0.50"),
            audio_input=Decimal("3.00"),
            text_output=Decimal("2.00"),
            audio_output=Decimal("12.00"),
        ),
    ),
    (
        "flash-live",
        TokenPrices(
            text_input=Decimal("0.50"),
            audio_input=Decimal("3.00"),
            text_output=Decimal("2.00"),
            audio_output=Decimal("12.00"),
        ),
    ),
    (
        "gemini-2.5-pro",
        TokenPrices(
            text_input=Decimal("1.25"),
            audio_input=Decimal("1.25"),
            text_output=Decimal("10.00"),
            audio_output=Decimal("10.00"),
        ),
    ),
    (
        "gemini-2.5-flash-lite",
        TokenPrices(
            text_input=Decimal("0.10"),
            audio_input=Decimal("0.30"),
            text_output=Decimal("0.40"),
            audio_output=Decimal("0.40"),
        ),
    ),
    (
        "gemini-2.5-flash",
        TokenPrices(
            text_input=Decimal("0.30"),
            audio_input=Decimal("1.00"),
            text_output=Decimal("2.50"),
            audio_output=Decimal("2.50"),
        ),
    ),
)


def prices_for_model(model: str) -> TokenPrices | None:
    name = model.lower()
    for fragment, prices in MODEL_PRICES_USD:
        if fragment in name:
            return prices
    return None


def _count(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    return int(value) if isinstance(value, (int, float)) and value > 0 else 0


def estimate_provider_cost_eur(usage_info: dict[str, Any] | None) -> Decimal | None:
    """Estimated LLM cost of a call in EUR, or None if any model is unpriced.

    ``usage_info["llm"]`` maps ``"<processor>|||<model>"`` to pipecat
    ``LLMTokenUsage`` dumps. Gemini reports prompt and completion counts gross
    of their audio share, so audio is priced separately and subtracted.
    """
    llm_usage = (usage_info or {}).get("llm") or {}
    if not llm_usage:
        return None

    total_usd = Decimal(0)
    for key, usage in llm_usage.items():
        model = key.split("|||", 1)[-1]
        prices = prices_for_model(model)
        if prices is None or not isinstance(usage, dict):
            return None
        audio_in = _count(usage, "input_audio_tokens")
        audio_out = _count(usage, "output_audio_tokens")
        text_in = max(_count(usage, "prompt_tokens") - audio_in, 0)
        text_out = max(_count(usage, "completion_tokens") - audio_out, 0)
        total_usd += (
            text_in * prices.text_input
            + audio_in * prices.audio_input
            + text_out * prices.text_output
            + audio_out * prices.audio_output
        ) / _MILLION
    return (total_usd * USD_TO_EUR).quantize(Decimal("0.0001"))
