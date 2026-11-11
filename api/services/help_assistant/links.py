"""The only places an answer may link to: in-app screens an owner uses, and
the website's contact form. Every other link the model writes is unwrapped to
plain text, and bare URLs are removed."""

from __future__ import annotations

import re
from typing import Final

CONTACT_URL: Final = "https://lightmove.ai/contact"

# Path -> screen name. ``{agent}`` is filled in with the workspace's agent.
ALLOWED_PATHS: Final[dict[str, str]] = {
    "/overview": "Home",
    "/usage": "Calls",
    "/follow-ups": "Follow-ups",
    "/bookings": "Bookings",
    "/reports": "Reports",
    "/workflow": "Voice agents",
    "/workflow/create": "New voice agent",
    "/workflow/{agent}/facts": "What your agent knows",
    "/workflow/{agent}/deployment": "Phone number",
    "/workflow/{agent}/home": "Agent dashboard",
    "/workflow/{agent}/settings": "Agent settings",
    "/workflow/{agent}/model": "Agent voice and model",
    "/telephony-configurations": "Telephony",
    "/integrations": "Integrations",
    "/settings": "Settings",
    "/team": "Members",
    "/settings/notifications": "Notifications",
    "/settings/reports": "Reports by email",
    "/billing": "Billing",
    "/settings/compliance": "Privacy & compliance",
    "/account": "Your account",
    "/api-keys": "API keys",
}
ALLOWED_EXTERNAL: Final = frozenset({CONTACT_URL})

_MD_LINK = re.compile(r"\[([^\]\n]{1,200})\]\(([^)\s]{1,300})\)")
_BARE_URL = re.compile(r"(?<![(\w])(?:https?://|www\.)[^\s)>\]]+", re.IGNORECASE)
_AGENT_PATH = re.compile(r"^/workflow/(?:\{agent\}|\d+)(/.*)?$")

# Where an agent screen goes when there is no single agent to fill in.
_AGENT_FALLBACK = "/workflow"


def resolve_href(href: str, agent_id: int | None) -> str | None:
    """The link to show for ``href``, or None when it isn't allowed."""
    href = href.strip()
    for external in ALLOWED_EXTERNAL:
        if href.startswith(external) and re.fullmatch(
            r"/?(\?reason=[a-z]{1,20})?", href[len(external) :]
        ):
            return href
    if not href.startswith("/") or href.startswith("//"):
        return None
    path, _, fragment = href.partition("#")
    if "?" in path:
        return None
    path = path.rstrip("/") or "/"
    match = _AGENT_PATH.match(path)
    template = f"/workflow/{{agent}}{match.group(1) or ''}" if match else path
    if template not in ALLOWED_PATHS:
        return None
    if "{agent}" in template:
        if agent_id is None:
            return _AGENT_FALLBACK
        path = template.replace("{agent}", str(agent_id))
    if fragment and re.fullmatch(r"[a-z0-9-]{1,40}", fragment):
        return f"{path}#{fragment}"
    return path


def sanitize_links(text: str, agent_id: int | None) -> tuple[str, list[str]]:
    """Rewrite markdown links to allowed targets; drop the rest.
    Returns the new text and the links kept, in order."""
    kept: list[str] = []
    placeholders: list[str] = []

    def _link(match: re.Match[str]) -> str:
        label, href = match.group(1), match.group(2)
        target = resolve_href(href, agent_id)
        if target is None:
            return label
        if target not in kept:
            kept.append(target)
        placeholders.append(f"[{label}]({target})")
        return f"\x00{len(placeholders) - 1}\x00"

    text = _MD_LINK.sub(_link, text)

    def _bare(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:")
        tail = match.group(0)[len(url) :]
        if url.startswith("https://") and resolve_href(url, None) is not None:
            if url not in kept:
                kept.append(url)
            return url + tail
        return "(link removed)" + tail

    text = _BARE_URL.sub(_bare, text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)
    return text, kept
