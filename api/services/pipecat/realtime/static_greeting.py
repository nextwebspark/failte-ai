from typing import Protocol, runtime_checkable


def format_static_greeting_prompt(greeting_text: str) -> str:
    # Speech-to-speech models read this as a user turn. Without saying who is
    # speaking, Gemini Live sometimes answers it in the caller's voice ("I'm
    # looking for a lifejacket..."), and agent prompts written for the
    # pipeline mode ("the greeting has already been spoken for you") make it
    # refuse or skip the line. Both are ruled out explicitly.
    return (
        "[Call event, not words from the caller] The phone call has just "
        "connected and nothing has been said yet. Your opening line has not "
        "been spoken yet: if your instructions say the greeting was already "
        "spoken for you, they mean this line, which you speak now. You are "
        "the agent on this call; never speak as the caller. Say the "
        "following opening line out loud, exactly as written, in a natural "
        "spoken voice, and then stop and wait for the caller to respond. "
        "Do not add anything before or after it.\n\n"
        f'"{greeting_text}"'
    )


def format_opening_line_instruction(greeting_text: str) -> str:
    """System-instruction section naming the opening line before the call starts.

    Gemini Live follows its system instruction far more reliably than a text
    turn: with only the greeting prompt it spoke the line about half the time
    under real call conditions (tools plus streaming audio), and with this
    section every time.
    """
    return (
        "# OPENING LINE\n\n"
        "You speak first on this call. When the call connects, say exactly "
        "this opening line and nothing else, then wait for the caller:\n"
        f'"{greeting_text}"\n'
        "Any instruction above saying the greeting was already spoken refers "
        "to this line."
    )


@runtime_checkable
class SupportsOpeningLine(Protocol):
    """A speech-to-speech service that can be told its greeting before connecting."""

    def set_opening_line(self, greeting_text: str | None) -> None: ...
