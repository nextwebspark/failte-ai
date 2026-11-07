"""Ready-to-demo accounts: four invented Irish businesses with a month of calls.

    python -m api.scripts.seed_demo_accounts            # create, or refresh the calls
    python -m api.scripts.seed_demo_accounts --reset    # delete the demo data, rebuild
    python -m api.scripts.seed_demo_accounts --delete   # delete the demo data only

Each business (``api/scripts/demo_businesses.py``) gets a workspace, an owner
(admin) and a staff login, an agent made from its starter template exactly as
the Create agent wizard makes it, daily and weekly email reports to the
owner, and 60-120 inbound phone calls over the last 30 days stored the way
real calls are: the call log, captured details, the call review, follow-up
marks, a transcript file and, for the newest calls, a recording synthesised
with Google TTS (two voices).

Running it again keeps the workspaces, users and agents and replaces the
seeded calls with a fresh month ending now, so the dashboard looks live.
Calls made on the day (test calls) are kept; ``--reset`` removes those too.

Only workspaces marked as demo ones are ever changed or deleted: provider id
``demo_lightmove_<slug>``, a ``DEMO_ACCOUNT`` configuration row, and every
member's address at ``@demo.lightmove.ai``. Runs only against a local or
development environment.

    DEMO_PASSWORD     the password for all eight logins (a printed local
                      default when unset)
    DEMO_TTS_CACHE    where synthesised speech is cached between runs
                      (default /tmp/lightmove-demo-tts)

No call is placed, no calendar is connected, no model reviews the calls
(the reviews are written by the seed, model "demo-seed") and nothing is
billed: no completion job runs for seeded calls.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import random
import re
import uuid
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlalchemy import select, text

from api.constants import APP_ROOT_DIR, ENVIRONMENT
from api.db import db_client
from api.db.models import UserModel, WorkflowModel, WorkflowRunModel
from api.enums import OrganizationConfigurationKey, OrgRole
from api.schemas.workflow_configurations import DEFAULT_CALL_DISCLOSURE_TEXT
from api.schemas.workflow_template import DuplicateTemplateRequest
from api.scripts.demo_businesses import (
    BOOKING_MADE,
    BUSINESSES,
    CALLBACK,
    SILENT,
    TRANSFER_NOT_ANSWERED,
    Business,
    Ctx,
    Plan,
    call_dates,
)
from api.services.call_review.categories import TEMPLATE_CATEGORY_FACT, reason_set
from api.services.call_review.review import CALL_REVIEW_KEY, REVIEW_VERSION
from api.services.dashboard.follow_ups import FollowUpKind, done_mark
from api.services.email_reports import service as email_reports
from api.services.email_reports.settings import add_recipient, record_change
from api.services.pipecat.realtime_feedback_events import (
    build_bot_text_event,
    build_function_call_end_event,
    build_function_call_start_event,
    build_node_transition_event,
    build_user_transcription_event,
    realtime_feedback_event_sort_key,
    stamp_realtime_feedback_event,
)
from api.services.storage import get_current_storage_backend, storage_fs
from api.utils.auth import hash_password
from api.utils.transcript import generate_transcript_text

DEMO_DOMAIN = "demo.lightmove.ai"
DEMO_PROVIDER_PREFIX = "demo_lightmove_"
DEMO_KEY = OrganizationConfigurationKey.DEMO_ACCOUNT.value
DEFAULT_PASSWORD = "LightMoveDemo2026!"
# Where "Pass calls to your team" puts callers through until the presenter
# sets a real number on the agent's "What your agent knows" page. Not a
# diallable number: a phone call's transfer to it fails like an unanswered one.
DEMO_TRANSFER_NUMBER = "+3530000000"
SEED_MARK = "demo_seed"
SEED_VERSION = 1
REVIEW_MODEL = "demo-seed"
TIMEZONE = ZoneInfo("Europe/Dublin")
SAMPLE_RATE = 16000
ALLOWED_ENVIRONMENTS = {"local", "development", "dev", "test"}

AGENT_VOICE = "en-US-Chirp3-HD-Charon"  # the platform default agent voice
FEMALE_VOICES = (
    "en-GB-Chirp3-HD-Aoede",
    "en-GB-Chirp3-HD-Kore",
    "en-GB-Chirp3-HD-Leda",
    "en-GB-Chirp3-HD-Zephyr",
)
MALE_VOICES = (
    "en-GB-Chirp3-HD-Puck",
    "en-GB-Chirp3-HD-Fenrir",
    "en-GB-Chirp3-HD-Orus",
    "en-GB-Chirp3-HD-Algenib",
)
TRANSFER_RING = APP_ROOT_DIR / "assets" / f"transfer_hold_ring_{SAMPLE_RATE}.wav"

# How Irish names sound, for the speech only; the transcript keeps the spelling.
SPOKEN_NAMES = {
    "Siobhán": "Shiv-awn",
    "Sinéad": "Shin-ade",
    "Gráinne": "Grawn-ya",
    "Róisín": "Ro-sheen",
    "Caoimhe": "Kee-va",
    "Eimear": "Ee-mer",
    "Áine": "Awn-ya",
    "Pádraig": "Paw-drig",
    "Seán": "Shawn",
    "Tadhg": "Tige",
    "Diarmuid": "Deer-mid",
    "Niamh": "Neeve",
    "Ciarán": "Keer-awn",
    "Aoife": "Ee-fa",
    "Cian": "Kee-an",
    "Eoin": "Owen",
    "Clodagh": "Clo-da",
    "Darragh": "Darra",
    "Colm": "Collum",
    "Fergal": "Fur-gal",
    "Ronan": "Ro-nan",
    "Donal": "Doe-nal",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")


def email_for(business: Business, role: str) -> str:
    return f"{business.slug}.{role}@{DEMO_DOMAIN}"


def provider_id_for(business: Business) -> str:
    return f"{DEMO_PROVIDER_PREFIX}{business.slug}"


# --- the demo guard ------------------------------------------------------------


class NotDemoError(RuntimeError):
    """An organization that isn't a seeded demo one."""


async def _member_emails(organization_id: int) -> list[str | None]:
    async with db_client.async_session() as session:
        rows = await session.execute(
            text(
                "select u.email from organization_users ou join users u "
                "on u.id = ou.user_id where ou.organization_id = :org"
            ),
            {"org": organization_id},
        )
        return [row.email for row in rows]


async def assert_demo_org(organization_id: int, provider_id: str) -> None:
    """Refuse unless every demo marker is present."""
    if not provider_id.startswith(DEMO_PROVIDER_PREFIX):
        raise NotDemoError(f"organization {organization_id}: not a demo provider id")
    if await db_client.get_configuration(organization_id, DEMO_KEY) is None:
        raise NotDemoError(f"organization {organization_id}: no {DEMO_KEY} row")
    emails = await _member_emails(organization_id)
    if any(not (e or "").lower().endswith(f"@{DEMO_DOMAIN}") for e in emails):
        raise NotDemoError(
            f"organization {organization_id}: has a member outside @{DEMO_DOMAIN}"
        )


async def _org_by_provider(provider_id: str):
    async with db_client.async_session() as session:
        row = await session.execute(
            text("select id, provider_id from organizations where provider_id = :p"),
            {"p": provider_id},
        )
        return row.first()


# --- users and the workspace -------------------------------------------------


async def ensure_user(email: str, name: str, password: str) -> UserModel:
    """A verified password account, as local signup makes one (the address is
    marked verified, as the emailed code would). The password is reset to
    ``password`` on every run."""
    account = await db_client.get_account_by_email(email)
    if account is None:
        account = await db_client.create_account(
            email=email,
            name=name,
            password_hash=hash_password(password),
            email_verified_at=_now(),
        )
    else:
        await db_client.set_password_hash(account.user_id, hash_password(password))
        if not account.is_email_verified:
            await db_client.mark_email_verified(account.user_id, _now())
    user = await db_client.get_user_by_id(account.user_id)
    assert user is not None
    return user


async def ensure_org(business: Business, owner: UserModel, staff: UserModel) -> int:
    """The business's workspace, made the way signup makes one (owner as
    admin, then bootstrapped), with the staff member added as staff."""
    from api.services.organization_bootstrap import ensure_organization_bootstrapped

    provider_id = provider_id_for(business)
    existing = await _org_by_provider(provider_id)
    if existing is None:
        organization, _ = await db_client.get_or_create_organization_by_provider_id(
            org_provider_id=provider_id, user_id=owner.id
        )
        organization_id = organization.id
        await db_client.upsert_configuration(
            organization_id,
            DEMO_KEY,
            {"slug": business.slug, "created_at": _now().isoformat()},
        )
    else:
        organization_id = existing.id
        await assert_demo_org(organization_id, provider_id)
    await db_client.update_organization_name(organization_id, business.name)
    await db_client.add_user_to_organization(
        owner.id, organization_id, role=OrgRole.ADMIN
    )
    await db_client.add_user_to_organization(
        staff.id, organization_id, role=OrgRole.STAFF, invited_by=owner.id
    )
    for user in (owner, staff):
        await db_client.update_user_selected_organization(user.id, organization_id)
    await ensure_organization_bootstrapped(
        organization_id, created_by=owner.provider_id
    )
    row = await db_client.get_configuration(organization_id, DEMO_KEY)
    await db_client.upsert_configuration(
        organization_id,
        DEMO_KEY,
        {
            **(row.value if row else {}),
            "slug": business.slug,
            "seeded_at": _now().isoformat(),
        },
    )
    return organization_id


# --- the agent -----------------------------------------------------------------


async def _template(name: str):
    from api.db.workflow_template_client import WorkflowTemplateClient

    for template in await WorkflowTemplateClient().get_all_workflow_templates():
        if template.template_name == name:
            return template
    raise RuntimeError(
        f"starter template {name!r} is missing: run python -m scripts.sync_agent_templates"
    )


async def ensure_agent(business: Business, organization_id: int, owner: UserModel):
    """The business's agent, made by the Create agent wizard's own endpoint
    from the matching starter template and the business's answers."""
    from api.routes.workflow import duplicate_workflow_template
    from api.services.auth.depends import resolve_org_membership

    template = await _template(business.template_name)
    name = f"{template.template_name} · {business.name}"
    workflow = await _agent(organization_id, name)
    if workflow is None:
        user = await db_client.get_user_by_id(owner.id)
        membership = await resolve_org_membership(user)
        await duplicate_workflow_template(
            DuplicateTemplateRequest(
                template_id=template.id,
                workflow_name=name,
                # The wizard's own "Number to put callers through to a
                # person" answer: a placeholder the presenter replaces.
                values={**business.facts, "transfer_number": DEMO_TRANSFER_NUMBER},
            ),
            membership=membership,
        )
        workflow = await _agent(organization_id, name)
    assert workflow is not None
    facts = workflow.template_context_variables or {}
    if facts.get(TEMPLATE_CATEGORY_FACT) != template.category:
        raise RuntimeError(f"{name}: template_category was not set")
    return workflow


async def _agent(organization_id: int, name: str) -> WorkflowModel | None:
    async with db_client.async_session() as session:
        return await session.scalar(
            select(WorkflowModel).where(
                WorkflowModel.organization_id == organization_id,
                WorkflowModel.name == name,
            )
        )


async def _transfer_function(organization_id: int) -> str:
    """The LLM function name of the agent's "put through" tool."""
    from api.services.workflow.tools.custom_tool import custom_tool_function_name

    async with db_client.async_session() as session:
        name = await session.scalar(
            text(
                "select name from tools where organization_id = :org and "
                "category = 'transfer_call' order by id limit 1"
            ),
            {"org": organization_id},
        )
    return custom_tool_function_name(name or "transfer_call")


# --- email reports -------------------------------------------------------------


async def ensure_email_reports(organization_id: int, owner: UserModel) -> None:
    """Daily and weekly reports to the owner's own (verified) address, which
    is confirmed straight away, as when an owner adds it themselves."""

    def change(settings):
        settings.daily = True
        settings.weekly = True
        if settings.find_email(owner.email) is None:
            add_recipient(
                settings,
                address=owner.email,
                by_user_id=owner.id,
                own_verified_email=owner.email,
                now=_now(),
            )
            record_change(
                settings,
                by_user_id=owner.id,
                by=owner.name,
                change=f"added {owner.email} (active); daily and weekly report on",
            )

    await email_reports.change_settings(organization_id, change)


# --- speech --------------------------------------------------------------------


@dataclass
class Speech:
    """Synthesised speech, cached on disk by voice and text."""

    cache: Path
    synthesised_chars: int = 0
    cached_chars: int = 0
    _token: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _limit: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(6))

    async def _bearer(self) -> str:
        from api.saas.voice_catalog import google_voices

        async with self._lock:
            creds = await google_voices._credentials_async(None)
            return creds.token

    async def pcm(self, voice: str, words: str) -> bytes:
        """16-bit mono PCM at SAMPLE_RATE."""
        key = hashlib.sha256(f"{voice}|{SAMPLE_RATE}|{words}".encode()).hexdigest()
        path = self.cache / f"{key}.pcm"
        if path.exists():
            self.cached_chars += len(words)
            return path.read_bytes()
        async with self._limit:
            token = await self._bearer()
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://texttospeech.googleapis.com/v1/text:synthesize",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "input": {"text": words},
                        "voice": {
                            "languageCode": "-".join(voice.split("-")[:2]),
                            "name": voice,
                        },
                        "audioConfig": {
                            "audioEncoding": "LINEAR16",
                            "sampleRateHertz": SAMPLE_RATE,
                        },
                    },
                )
        if response.status_code != 200:
            raise RuntimeError(f"TTS {response.status_code}: {response.text[:200]}")
        audio = base64.b64decode(response.json()["audioContent"])
        with wave.open(io.BytesIO(audio)) as wav:
            pcm = wav.readframes(wav.getnframes())
        self.synthesised_chars += len(words)
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pcm)
        return pcm


def spoken(words: str) -> str:
    """What the voice reads: names respelled, phone numbers digit by digit."""
    for name, sound in SPOKEN_NAMES.items():
        words = words.replace(name, sound)
    return re.sub(
        r"\b(\d{3}) (\d{3}) (\d{4})\b",
        lambda m: ", ".join(" ".join(group) for group in m.groups()),
        words,
    )


def caller_voice(ctx: Ctx) -> str:
    voices = FEMALE_VOICES if ctx.caller.female else MALE_VOICES
    digest = hashlib.sha256(ctx.caller.name.encode()).digest()
    return voices[digest[0] % len(voices)]


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * SAMPLE_RATE)


def _ring(seconds: float) -> bytes:
    """The hold ring callers hear while a transfer rings out."""
    try:
        with wave.open(str(TRANSFER_RING)) as wav:
            loop = wav.readframes(wav.getnframes())
    except (OSError, wave.Error):
        return _silence(seconds)
    need = int(seconds * SAMPLE_RATE) * 2
    out = (loop * (need // max(1, len(loop)) + 1))[:need]
    return out


def _wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


# --- one call ------------------------------------------------------------------


@dataclass
class Agent:
    workflow: WorkflowModel
    node_names: dict[str, str]
    greeting: str
    transfer_function: str
    category: str
    facts: dict[str, Any]
    fields: list[str]


def _render_placeholders(value: str, facts: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).removeprefix("initial_context.")
        return str(facts.get(key) or (match.group(2) or "").strip())

    return re.sub(
        r"\{\{\s*([\w.]+)\s*(?:\|\s*(?:fallback\s*:)?([^}]*))?\}\}", replace, value
    )


def agent_shape(workflow: WorkflowModel, transfer_function: str) -> Agent:
    definition = workflow.workflow_definition or {}
    facts = workflow.template_context_variables or {}
    nodes = {n["id"]: n for n in definition.get("nodes", [])}
    greeting = _render_placeholders(
        (nodes.get("start", {}).get("data") or {}).get("greeting") or "", facts
    )
    fields: list[str] = []
    for node in nodes.values():
        for item in (node.get("data") or {}).get("extraction_variables") or []:
            name = item.get("name") if isinstance(item, dict) else None
            if name and name not in fields:
                fields.append(name)
    return Agent(
        workflow=workflow,
        node_names={
            k: (n.get("data") or {}).get("name") or k for k, n in nodes.items()
        },
        greeting=f"{DEFAULT_CALL_DISCLOSURE_TEXT}\n\n{greeting}",
        transfer_function=transfer_function,
        category=str(facts.get(TEMPLATE_CATEGORY_FACT) or "general"),
        facts=facts,
        fields=fields,
    )


@dataclass
class Rendered:
    events: list[dict]
    duration: float
    tool_results: list[dict]
    nodes_visited: list[str]
    mixed: bytes | None = None
    user: bytes | None = None
    bot: bytes | None = None


async def render(
    plan: Plan,
    ctx: Ctx,
    agent: Agent,
    start: datetime,
    speech: Speech | None,
) -> Rendered:
    """The call log (and with ``speech`` the audio) of one planned call."""
    rng = random.Random(f"timing:{ctx.caller.name}:{start.isoformat()}")
    voice = caller_voice(ctx)
    events: list[dict] = []
    tool_results: list[dict] = []
    mixed: list[bytes] = []
    user_track: list[bytes] = []
    bot_track: list[bytes] = []
    cursor = 0.0
    # A live call's greeting is turn 1; each caller utterance starts the next.
    turn = 1
    node = "start"
    visited = [agent.node_names["start"]]
    visit_id = f"visit-{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}"

    def at(offset: float) -> str:
        return _iso(start + timedelta(seconds=offset))

    def add(event: dict, offset: float, *, with_node: bool = False) -> None:
        events.append(
            stamp_realtime_feedback_event(
                event,
                timestamp=at(offset),
                turn=turn,
                node_id=node if with_node else None,
                node_name=agent.node_names.get(node) if with_node else None,
            )
        )

    def pad(seconds: float, *, ring: bool = False) -> None:
        nonlocal cursor
        if speech is not None:
            chunk = _ring(seconds) if ring else _silence(seconds)
            mixed.append(chunk)
            user_track.append(_silence(seconds))
            bot_track.append(chunk)
        cursor += seconds

    async def say(who: str, words: str) -> tuple[float, float]:
        nonlocal cursor
        begin = cursor
        if speech is not None:
            pcm = await speech.pcm(
                AGENT_VOICE if who == "agent" else voice, spoken(words)
            )
            length = len(pcm) / 2 / SAMPLE_RATE
            mixed.append(pcm)
            (bot_track if who == "agent" else user_track).append(pcm)
            (user_track if who == "agent" else bot_track).append(_silence(length))
        else:
            length = len(words) / (14.5 if who == "agent" else 13.0) + 0.3
        cursor += length
        return begin, cursor

    def transition(target: str) -> None:
        nonlocal node
        add(
            build_node_transition_event(
                node_id=target,
                node_name=agent.node_names.get(target),
                previous_node_id=node if events else None,
                previous_node_name=agent.node_names.get(node) if events else None,
                allow_interrupt=target not in ("start", "end", "end_early"),
            ),
            cursor,
            with_node=False,
        )
        events[-1]["node_id"] = target
        events[-1]["node_name"] = agent.node_names.get(target)
        node = target
        name = agent.node_names.get(target)
        if name and name not in visited:
            visited.append(name)

    # The call opens on the start step; the agent greets after a ring.
    pad(rng.uniform(0.4, 0.8))
    events.append(
        stamp_realtime_feedback_event(
            build_node_transition_event(
                node_id="start",
                node_name=agent.node_names["start"],
                previous_node_id=None,
                previous_node_name=None,
            ),
            timestamp=at(0.05),
            turn=1,
            node_id="start",
            node_name=agent.node_names["start"],
        )
    )
    for step in plan.steps:
        if step.kind in ("agent", "caller"):
            # The greeting is spoken as two paragraphs and logged as one line.
            words = agent.greeting if step is plan.steps[0] else step.text
            if step.kind == "caller":
                turn += 1
            begin, end = await say(step.kind, words)
            words = words.replace("\n\n", " ")
            event = (
                build_bot_text_event(
                    text=words, timestamp=at(begin), end_timestamp=at(end)
                )
                if step.kind == "agent"
                else build_user_transcription_event(
                    text=words, final=True, timestamp=at(begin), end_timestamp=at(end)
                )
            )
            # Logged when the utterance ends, as the live transcript does.
            add(event, end, with_node=True)
            pad(
                rng.uniform(0.45, 0.9)
                if step.kind == "agent"
                else rng.uniform(0.6, 1.3)
            )
        elif step.kind == "move":
            call_id = f"call_{rng.randint(1000000, 9999999)}"
            add(
                build_function_call_start_event(
                    function_name=step.function, tool_call_id=call_id, arguments={}
                ),
                cursor,
            )
            pad(rng.uniform(0.6, 1.1))
            transition(step.target)
            pad(0.1)
            add(
                build_function_call_end_event(
                    function_name=step.function,
                    tool_call_id=call_id,
                    result={"status": "done"},
                ),
                cursor,
            )
            pad(rng.uniform(0.5, 1.0))
        elif step.kind == "tool":
            call_id = f"call_{rng.randint(1000000, 9999999)}"
            add(
                build_function_call_start_event(
                    function_name=step.function,
                    tool_call_id=call_id,
                    arguments=step.arguments,
                ),
                cursor,
            )
            pad(rng.uniform(0.7, 1.4))
            result = json.dumps(step.result)
            add(
                build_function_call_end_event(
                    function_name=step.function, tool_call_id=call_id, result=result
                ),
                cursor,
            )
            tool_results.append(
                {
                    "visit_id": visit_id,
                    "tool_call_id": call_id,
                    "function_name": step.function,
                    "arguments": step.arguments,
                    "status": "completed",
                    "result": result,
                }
            )
            pad(rng.uniform(0.3, 0.7))
        elif step.kind == "transfer":
            call_id = f"call_{rng.randint(1000000, 9999999)}"
            add(
                build_function_call_start_event(
                    function_name=agent.transfer_function,
                    tool_call_id=call_id,
                    arguments={},
                ),
                cursor,
            )
            sid = f"CA{rng.getrandbits(128):032x}"
            if step.answered:
                pad(rng.uniform(6, 14), ring=True)
                result = {
                    "status": "transfer_success",
                    "message": "Transfer destination answered - connecting calls",
                    "conference_id": f"transfer-{sid[2:14]}",
                }
            else:
                pad(rng.uniform(24, 30), ring=True)
                # What the engine hands the agent after the carrier reports
                # no answer (_handle_transfer_result, action transfer_failed).
                result = {
                    "status": "transfer_failed",
                    "reason": "no_answer",
                    "message": "The transfer call was not answered. The person may be busy or unavailable right now.",
                }
            add(
                build_function_call_end_event(
                    function_name=agent.transfer_function,
                    tool_call_id=call_id,
                    result=result,
                ),
                cursor,
            )
            pad(0.4)
    if not plan.speech:
        pad(plan.silence_seconds)
    duration = cursor
    events.sort(key=realtime_feedback_event_sort_key)

    def joined(chunks: list[bytes]) -> bytes | None:
        return _wav(b"".join(chunks)) if speech is not None else None

    return Rendered(
        events=events,
        duration=round(duration, 3),
        tool_results=tool_results,
        nodes_visited=visited,
        mixed=joined(mixed),
        user=joined(user_track),
        bot=joined(bot_track),
    )


def _review(plan: Plan, agent: Agent, created: datetime) -> dict:
    reasons = reason_set(agent.category)
    return {
        "version": REVIEW_VERSION,
        "summary": plan.summary,
        "reason": plan.reason,
        "reason_label": reasons.label(plan.reason),
        "unanswered_questions": list(plan.unanswered),
        "time_was_full": plan.time_was_full,
        "model": REVIEW_MODEL,
        "created_at": created.isoformat(),
    }


def _follow_up_kinds(plan: Plan) -> list[str | None]:
    """Which follow-ups the call raises: None for the call's own mark
    (callback, transfer nobody answered), else the call-review kind."""
    kinds: list[str | None] = []
    if plan.outcome in (CALLBACK, TRANSFER_NOT_ANSWERED):
        kinds.append(None)
    if plan.unanswered:
        kinds.append(FollowUpKind.UNANSWERED_QUESTION.value)
    if plan.time_was_full and plan.outcome != BOOKING_MADE:
        kinds.append(FollowUpKind.TIME_WAS_FULL.value)
    return kinds


def _marks(
    plan: Plan,
    start: datetime,
    now: datetime,
    rng: random.Random,
    people: list[UserModel],
) -> dict:
    """Follow-up done marks, mostly by the staff member (some by the
    owner); the newest ones are left open."""
    age = now - start
    annotations: dict[str, Any] = {}
    kinds = _follow_up_kinds(plan)
    if plan.outcome == SILENT:
        # A caller who rang twice in a row without reaching anyone raises a
        # "rang more than once" follow-up on their latest call; it is marked
        # on the call itself, like a callback.
        kinds.append(None)
    for kind in kinds:
        # Older than three days: sorted. The last few days: about half.
        # The last few hours: still waiting.
        chance = (
            1.0 if age > timedelta(days=3) else 0.5 if age > timedelta(hours=4) else 0.0
        )
        if rng.random() >= chance:
            continue
        done_at = min(
            now - timedelta(minutes=3), start + timedelta(minutes=rng.randint(12, 300))
        )
        who = people[0] if rng.random() < 0.65 else people[1]
        mark = done_mark(user_id=who.id, name=who.name, email=who.email, now=done_at)
        if kind is None:
            annotations["follow_up"] = mark
        else:
            annotations.setdefault("follow_up_kinds", {})[kind] = mark
    return annotations


def _choose(business: Business, rng: random.Random):
    weights = [w for w, _ in business.scenarios]
    return rng.choices([s for _, s in business.scenarios], weights)[0]


def _caller(business: Business, rng: random.Random):
    # A few regulars ring more than once.
    pool = business.callers
    if rng.random() < 0.3:
        return rng.choice(pool[:8])
    return rng.choice(pool)


# --- seeding the calls ---------------------------------------------------------


async def seeded_runs(organization_id: int) -> list[WorkflowRunModel]:
    async with db_client.async_session() as session:
        result = await session.execute(
            select(WorkflowRunModel)
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(
                WorkflowModel.organization_id == organization_id,
                text(f"workflow_runs.extra->>'{SEED_MARK}' is not null"),
            )
        )
        return list(result.scalars().all())


def _object_keys(run: WorkflowRunModel) -> list[str]:
    keys = [run.recording_url, run.transcript_url]
    for track in ((run.extra or {}).get("recordings") or {}).values():
        if isinstance(track, dict):
            keys.append(track.get("storage_key"))
    return [k for k in keys if k]


async def delete_seeded_calls(organization_id: int) -> int:
    runs = await seeded_runs(organization_id)
    for run in runs:
        for key in _object_keys(run):
            await storage_fs.adelete_file(key)
    if runs:
        async with db_client.async_session() as session:
            await session.execute(
                text("delete from workflow_runs where id = any(:ids)"),
                {"ids": [r.id for r in runs]},
            )
            await session.commit()
    return len(runs)


async def _put(key: str, data: bytes, content_type: str) -> None:
    """Upload, typed so the browser plays or shows it inline (S3 types WAVs
    when it signs; MinIO serves what was stored)."""
    client = getattr(storage_fs, "client", None)
    bucket = getattr(storage_fs, "bucket_name", None)
    if client is not None and bucket and hasattr(client, "put_object"):
        await asyncio.to_thread(
            client.put_object,
            bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )
        return
    if not await storage_fs.acreate_file_from_bytes(key, data):
        raise RuntimeError(f"upload failed: {key}")


@dataclass
class Totals:
    calls: int = 0
    recordings: int = 0
    booking_calls: int = 0
    today: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)


async def seed_calls(
    business: Business,
    organization_id: int,
    agent: Agent,
    people: list[UserModel],
    *,
    now: datetime,
    recordings: int,
    speech: Speech | None,
) -> Totals:
    """Replace the business's seeded calls with a month ending ``now``."""
    await delete_seeded_calls(organization_id)
    now_local = now.astimezone(TIMEZONE)
    starts = call_dates(business, now_local)
    backend = get_current_storage_backend().value
    totals = Totals()
    definition_id = agent.workflow.released_definition_id
    rows: list[tuple[WorkflowRunModel, Rendered]] = []
    for index, start_local in enumerate(starts):
        rng = random.Random(f"{business.slug}:call:{index}")
        caller = _caller(business, rng)
        ctx = Ctx(
            rng=rng,
            caller=caller,
            started=start_local,
            business=business,
            greeting=agent.greeting,
        )
        plan = _choose(business, rng)(ctx)
        start = start_local.astimezone(UTC)
        recorded = index < recordings and speech is not None
        rendered = await render(plan, ctx, agent, start, speech if recorded else None)
        end = start + timedelta(seconds=rendered.duration)
        captured = {name: "" for name in agent.fields}
        captured.update({k: v for k, v in plan.captured.items() if k in captured})
        tags = [plan.status] + (["user_speech"] if plan.speech else [])
        gathered: dict[str, Any] = {
            "call_id": f"CA{rng.getrandbits(128):032x}",
            "nodes_visited": rendered.nodes_visited,
            **captured,
            "extracted_variables": dict(captured),
            "call_status": plan.status,
            "call_disposition": plan.status,
            "mapped_call_disposition": plan.status,
            "call_tags": tags,
        }
        if rendered.tool_results:
            gathered["tool_results"] = rendered.tool_results
        annotations: dict[str, Any] = {
            CALL_REVIEW_KEY: _review(
                plan, agent, end + timedelta(seconds=rng.randint(8, 40))
            )
        }
        marks = _marks(plan, start, now, rng, people)
        annotations.update(marks)
        run = WorkflowRunModel(
            name=f"WR-TEL-IN-{rng.randint(0, 99_999_999):08d}",
            workflow_id=agent.workflow.id,
            definition_id=definition_id,
            mode="twilio",
            call_type="inbound",
            state="completed",
            is_completed=True,
            storage_backend=backend,
            usage_info={"call_duration_seconds": rendered.duration},
            cost_info={},
            initial_context={
                **agent.facts,
                "caller_number": caller.number or "anonymous",
                "called_number": business.called_number,
                "direction": "inbound",
                "provider": "twilio",
            },
            gathered_context=gathered,
            logs={"realtime_feedback_events": rendered.events},
            annotations=annotations,
            extra={SEED_MARK: {"version": SEED_VERSION, "business": business.slug}},
            created_at=start,
            public_access_token=str(uuid.UUID(int=rng.getrandbits(128))),
        )
        rows.append((run, rendered))
        totals.calls += 1
        totals.outcomes[plan.outcome] = totals.outcomes.get(plan.outcome, 0) + 1
        if plan.outcome == BOOKING_MADE:
            totals.booking_calls += 1
        if start_local.date() == now_local.date():
            totals.today += 1
    async with db_client.async_session() as session:
        session.add_all([run for run, _ in rows])
        await session.flush()
        for run, _ in rows:
            run.initial_context = {**run.initial_context, "workflow_run_id": run.id}
        # Read before the commit, which expires the rows.
        ids = [(run.id, rendered) for run, rendered in rows]
        await session.commit()
    for run_id, rendered in ids:
        update: dict[str, Any] = {}
        transcript = generate_transcript_text(rendered.events)
        if transcript:
            key = f"transcripts/{run_id}.txt"
            await _put(key, transcript.encode("utf-8"), "text/plain; charset=utf-8")
            update["transcript_url"] = key
        if rendered.mixed:
            recordings_meta = {}
            for track, data, key in (
                ("mixed", rendered.mixed, f"recordings/{run_id}.wav"),
                ("user", rendered.user, f"recordings/{run_id}/user.wav"),
                ("bot", rendered.bot, f"recordings/{run_id}/bot.wav"),
            ):
                await _put(key, data, "audio/wav")
                recordings_meta[track] = {
                    "storage_key": key,
                    "storage_backend": backend,
                    "format": "wav",
                    "track": track,
                }
            update["recording_url"] = f"recordings/{run_id}.wav"
            update["recordings"] = recordings_meta
            totals.recordings += 1
        async with db_client.async_session() as session:
            run = await session.get(WorkflowRunModel, run_id)
            run.transcript_url = update.get("transcript_url")
            if "recording_url" in update:
                run.recording_url = update["recording_url"]
                run.extra = {**(run.extra or {}), "recordings": update["recordings"]}
            await session.commit()
    return totals


# --- deleting --------------------------------------------------------------------


async def delete_demo_org(business: Business) -> bool:
    """Delete one demo workspace, its users and every stored file of its
    calls. Refuses anything that isn't a marked demo workspace."""
    provider_id = provider_id_for(business)
    org = await _org_by_provider(provider_id)
    if org is None:
        return False
    await assert_demo_org(org.id, provider_id)
    async with db_client.async_session() as session:
        runs = await session.execute(
            select(WorkflowRunModel)
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(WorkflowModel.organization_id == org.id)
        )
        runs = list(runs.scalars().all())
    for run in runs:
        for key in _object_keys(run):
            await storage_fs.adelete_file(key)
    params = {"org": org.id}
    async with db_client.async_session() as session:
        member_ids = [
            row.user_id
            for row in await session.execute(
                text(
                    "select user_id from organization_users where organization_id = :org"
                ),
                params,
            )
        ]
        workflows = "select id from workflows where organization_id = :org"
        for statement in (
            f"delete from workflow_runs where workflow_id in ({workflows})",
            "delete from campaigns where organization_id = :org",
            f"update workflows set released_definition_id = null where id in ({workflows})",
            f"delete from workflow_definitions where workflow_id in ({workflows})",
            "delete from workflows where organization_id = :org",
            "delete from integrations where organization_id = :org",
            "delete from folders where organization_id = :org",
            "delete from organization_usage_cycles where organization_id = :org",
            "delete from organization_users where organization_id = :org",
            "update users set selected_organization_id = null where selected_organization_id = :org",
        ):
            await session.execute(text(statement), params)
        # The members, unless they belong to another workspace too.
        for user_id in member_ids:
            other = await session.scalar(
                text("select count(*) from organization_users where user_id = :u"),
                {"u": user_id},
            )
            email = await session.scalar(
                text("select email from users where id = :u"), {"u": user_id}
            )
            if not other and (email or "").lower().endswith(f"@{DEMO_DOMAIN}"):
                await session.execute(
                    text("delete from users where id = :u"), {"u": user_id}
                )
        await session.execute(text("delete from organizations where id = :org"), params)
        await session.commit()
    return True


# --- main ----------------------------------------------------------------------


async def seed_business(
    business: Business,
    *,
    password: str,
    now: datetime,
    recordings: int,
    speech: Speech | None,
) -> dict:
    owner = await ensure_user(
        email_for(business, "owner"), business.owner_name, password
    )
    staff = await ensure_user(
        email_for(business, "staff"), business.staff_name, password
    )
    organization_id = await ensure_org(business, owner, staff)
    owner = await db_client.get_user_by_id(owner.id)
    workflow = await ensure_agent(business, organization_id, owner)
    await ensure_email_reports(organization_id, owner)
    agent = agent_shape(workflow, await _transfer_function(organization_id))
    before = (speech.synthesised_chars, speech.cached_chars) if speech else (0, 0)
    totals = await seed_calls(
        business,
        organization_id,
        agent,
        [staff, owner],
        now=now,
        recordings=recordings,
        speech=speech,
    )
    # Counted the way Follow-ups counts them.
    from api.services.dashboard.follow_ups import FollowUpStatus
    from api.services.dashboard.service import follow_up_list

    follow_ups = await follow_up_list(
        organization_id=organization_id, status=FollowUpStatus.OPEN, workflow_id=None
    )
    return {
        "business": business.name,
        "organization_id": organization_id,
        "agent_id": workflow.id,
        "owner": owner.email,
        "staff": staff.email,
        "calls": totals.calls,
        "calls_today": totals.today,
        "recordings": totals.recordings,
        "tts_chars_synthesised": (speech.synthesised_chars - before[0])
        if speech
        else 0,
        "tts_chars_from_cache": (speech.cached_chars - before[1]) if speech else 0,
        "follow_ups_open": follow_ups["open_count"],
        "follow_ups_done": follow_ups["done_count"],
        "booking_calls": totals.booking_calls,
        "outcomes": dict(sorted(totals.outcomes.items())),
    }


async def _main(args: argparse.Namespace) -> None:
    if ENVIRONMENT not in ALLOWED_ENVIRONMENTS:
        raise SystemExit(
            f"Refusing to run with ENVIRONMENT={ENVIRONMENT!r}: demo accounts are "
            "for local and development databases only."
        )
    businesses = [b for b in BUSINESSES if not args.only or b.slug in args.only]
    if args.reset or args.delete:
        for business in businesses:
            deleted = await delete_demo_org(business)
            print(f"{business.slug}: {'deleted' if deleted else 'nothing to delete'}")
        if args.delete:
            return
    password = os.environ.get("DEMO_PASSWORD") or ""
    if not password:
        password = DEFAULT_PASSWORD
        print(f"DEMO_PASSWORD is not set; using the local default: {DEFAULT_PASSWORD}")
    speech = (
        None
        if args.no_audio
        else Speech(Path(os.environ.get("DEMO_TTS_CACHE") or "/tmp/lightmove-demo-tts"))
    )
    now = _now()
    report = []
    for business in businesses:
        result = await seed_business(
            business,
            password=password,
            now=now,
            recordings=args.recordings,
            speech=speech,
        )
        report.append(result)
        print(json.dumps(result, ensure_ascii=False))
    if speech:
        print(
            f"TTS characters synthesised this run: {speech.synthesised_chars} "
            f"(from cache: {speech.cached_chars})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the demo workspaces first, then rebuild",
    )
    parser.add_argument(
        "--delete", action="store_true", help="only delete the demo workspaces"
    )
    parser.add_argument(
        "--only", action="append", help="only this business slug (repeatable)"
    )
    parser.add_argument(
        "--recordings",
        type=int,
        default=20,
        help="recordings for the newest N calls of each business (default 20)",
    )
    parser.add_argument(
        "--no-audio", action="store_true", help="no recordings (no TTS calls)"
    )
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="WARNING")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
