"""Ready-made agents offered first in the Create agent dialog.

Each starter is a workflow with ``{{key}}`` placeholders plus the setup
questions that fill them, so a user only answers questions about their
business. ``python -m scripts.sync_agent_templates`` writes them to the
``workflow_templates`` table.
"""

from dataclasses import dataclass
from typing import Any

from api.schemas.workflow_template import TemplateSetupField
from api.services.workflow.agent_builder import (
    AgentSpec,
    CapturedFieldSpec,
    StageSpec,
    assemble_workflow_definition,
)


@dataclass(frozen=True, slots=True)
class StarterTemplate:
    name: str
    description: str
    setup_fields: list[TemplateSetupField]
    definition: dict[str, Any]


_RECEPTIONIST = AgentSpec(
    name="AI Receptionist",
    persona=(
        "You are the friendly receptionist for {{business_name}}. "
        "About the business: {{business_description}}\n\n"
        "Opening hours: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed. Offer to take a message instead.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other things callers often ask about: {{extra_info | fallback:nothing else.}}\n\n"
        "Answer questions using only these facts. Never guess prices, availability "
        "or anything not listed here: offer to take a message so the team can "
        "call back."
    ),
    greeting="Hi, thanks for calling {{business_name}}. How can I help you today?",
    opening=StageSpec(
        name="Help the caller",
        prompt=(
            "Find out why the person is calling. If you can answer from what you "
            "know about the business, answer briefly and ask if there is anything "
            "else. If they want to book, change an appointment, get a callback or "
            "speak to someone, explain that you will take a message for the team."
        ),
        done_when=(
            "The caller needs something you cannot do yourself, such as a booking, "
            "a callback or speaking to a person."
        ),
    ),
    stages=[
        StageSpec(
            name="Take a message",
            prompt=(
                "Take a message for the team. Ask for the caller's name, the best "
                "number to reach them, and a short reason for the call, one "
                "question at a time. Read the number back to confirm it."
            ),
            done_when=(
                "You have the caller's name, a confirmed phone number and the "
                "reason for the call."
            ),
        )
    ],
    closing_prompt=(
        "Tell the caller the team will get back to them during opening hours, "
        "thank them for calling {{business_name}}, and say goodbye."
    ),
    end_call_when=(
        "The caller has what they need and wants to go, says goodbye, or it is a "
        "wrong number or a sales call."
    ),
    captured_fields=[
        CapturedFieldSpec(name="caller_name", description="The caller's name."),
        CapturedFieldSpec(
            name="callback_number", description="The best number to call them back on."
        ),
        CapturedFieldSpec(
            name="call_reason", description="Why they called, in one line."
        ),
    ],
)

STARTER_TEMPLATES: list[StarterTemplate] = [
    StarterTemplate(
        name="AI Receptionist",
        description=(
            "Answers your calls, tells callers about your business and takes a "
            "message when your team needs to call back."
        ),
        setup_fields=[
            TemplateSetupField(
                key="business_name",
                label="Business name",
                placeholder="Bloom Dental",
                max_length=120,
            ),
            TemplateSetupField(
                key="business_description",
                label="What does your business do?",
                type="textarea",
                placeholder=(
                    "Family dental practice in Dublin. Check-ups, cleaning, "
                    "whitening and emergency appointments."
                ),
            ),
            TemplateSetupField(
                key="opening_hours",
                label="Opening hours",
                placeholder="Mon–Fri 9am–6pm, Sat 10am–2pm, closed Sunday",
                max_length=300,
            ),
            TemplateSetupField(
                key="address",
                label="Address",
                placeholder="12 Main Street, Dublin 2",
                required=False,
                max_length=300,
            ),
            TemplateSetupField(
                key="website",
                label="Website",
                type="url",
                placeholder="https://bloomdental.ie",
                required=False,
                max_length=300,
            ),
            TemplateSetupField(
                key="extra_info",
                label="Anything else callers often ask?",
                type="textarea",
                help="Parking, prices, payment options, languages you speak.",
                placeholder="Free parking behind the building. We take card and cash.",
                required=False,
                max_length=1500,
            ),
        ],
        definition=assemble_workflow_definition(_RECEPTIONIST, "INBOUND"),
    ),
]
