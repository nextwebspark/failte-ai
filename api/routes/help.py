"""In-app Help: ask the help assistant, rate an answer, and contact support.

Any signed-in member of a workspace may use these. The assistant can't see
the workspace's data; it answers from the hand-written guides only.
"""

import re
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user, requires
from api.services.auth.permissions import Permission
from api.services.help_assistant import guardrails
from api.services.help_assistant.assistant import answer_question
from api.services.help_assistant.feedback import HelpFeedbackIn, record_feedback
from api.services.help_assistant.tickets import (
    Ticket,
    TicketIn,
    TicketSummary,
    create_ticket,
    list_tickets,
)
from api.services.rate_limit import RateLimiter, get_rate_limiter

router = APIRouter(prefix="/help", tags=["help"])

ASK_LIMIT_PER_USER = 30
ASK_LIMIT_PER_WORKSPACE = 200
ASK_WINDOW = timedelta(hours=1)
TICKET_LIMIT_PER_USER = 5
TICKET_LIMIT_PER_WORKSPACE = 20
TICKET_WINDOW = timedelta(hours=1)
FEEDBACK_LIMIT_PER_USER = 60


class HelpAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=guardrails.MAX_QUESTION_CHARS)
    # The screen the person is on, e.g. /workflow/12/deployment.
    page: str | None = Field(default=None, max_length=300)


class HelpAnswerOut(BaseModel):
    id: str
    kind: Literal["answer", "not_covered", "off_topic", "unavailable"]
    # Markdown: bold, numbered steps and links to allowed in-app screens only.
    answer: str
    links: list[str]
    sources: list[str]


class HelpTicketsOut(BaseModel):
    tickets: list[TicketSummary]


class HelpTicketOut(BaseModel):
    ticket: TicketSummary


def _organization(user: UserModel) -> int:
    if user.selected_organization_id is None:
        raise HTTPException(status_code=403, detail="No workspace selected")
    return user.selected_organization_id


async def _limit(
    limiter: RateLimiter, checks: list[tuple[str, int]], window: timedelta, what: str
) -> None:
    for key, limit in checks:
        if not await limiter.allow(key, limit=limit, window=window):
            raise HTTPException(
                status_code=429,
                detail=f"You've sent a lot of {what} in the last hour. Please try again later.",
            )


async def _agent_for(organization_id: int, page: str | None) -> int | None:
    """The agent an agent-screen link should open: the one on screen, else the
    workspace's only agent. None means the agents list."""
    match = re.match(r"^/workflow/(\d+)(?:/|$)", page or "")
    if match:
        workflow = await db_client.get_workflow(
            int(match.group(1)), organization_id=organization_id
        )
        if workflow is not None:
            return workflow.id
    agents = await db_client.get_all_workflows_for_listing(
        organization_id=organization_id, status="active"
    )
    return agents[0].id if len(agents) == 1 else None


@router.post(
    "/ask",
    response_model=HelpAnswerOut,
    dependencies=requires(Permission.AGENTS_READ),
)
async def ask_help(
    body: HelpAskIn,
    user: Annotated[UserModel, Depends(get_user)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
):
    """Answer a question about using LightMove from the help guides."""
    organization_id = _organization(user)
    await _limit(
        limiter,
        [
            (f"help-ask:user:{user.id}", ASK_LIMIT_PER_USER),
            (f"help-ask:org:{organization_id}", ASK_LIMIT_PER_WORKSPACE),
        ],
        ASK_WINDOW,
        "questions",
    )
    reply = await answer_question(
        organization_id=organization_id,
        user_id=user.id,
        question=body.question,
        page=body.page,
        agent_id=await _agent_for(organization_id, body.page),
    )
    return HelpAnswerOut(
        id=reply.id,
        kind=reply.kind,
        answer=reply.answer,
        links=reply.links,
        sources=reply.sources,
    )


@router.post(
    "/feedback",
    status_code=204,
    dependencies=requires(Permission.AGENTS_READ),
)
async def help_feedback(
    body: HelpFeedbackIn,
    user: Annotated[UserModel, Depends(get_user)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
):
    """Thumbs up or down on an answer (metadata only, no text)."""
    organization_id = _organization(user)
    await _limit(
        limiter,
        [(f"help-feedback:user:{user.id}", FEEDBACK_LIMIT_PER_USER)],
        ASK_WINDOW,
        "ratings",
    )
    await record_feedback(organization_id, body)


@router.get(
    "/tickets",
    response_model=HelpTicketsOut,
    dependencies=requires(Permission.AGENTS_READ),
)
async def get_help_tickets(user: Annotated[UserModel, Depends(get_user)]):
    """Your recent support tickets in this workspace and their status."""
    organization_id = _organization(user)
    return HelpTicketsOut(tickets=await list_tickets(organization_id, user.id))


@router.post(
    "/tickets",
    response_model=HelpTicketOut,
    dependencies=requires(Permission.AGENTS_READ),
)
async def create_help_ticket(
    body: TicketIn,
    user: Annotated[UserModel, Depends(get_user)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
):
    """Send a ticket to the LightMove team. They're emailed, and so are you."""
    organization_id = _organization(user)
    await _limit(
        limiter,
        [
            (f"help-ticket:user:{user.id}", TICKET_LIMIT_PER_USER),
            (f"help-ticket:org:{organization_id}", TICKET_LIMIT_PER_WORKSPACE),
        ],
        TICKET_WINDOW,
        "messages",
    )
    organization = await db_client.get_organization_by_id(organization_id)
    ticket: Ticket = await create_ticket(
        organization_id=organization_id,
        organization_name=getattr(organization, "name", None),
        user_id=user.id,
        user_email=getattr(user, "email", None),
        body=body,
    )
    return HelpTicketOut(ticket=TicketSummary.model_validate(ticket.model_dump()))
