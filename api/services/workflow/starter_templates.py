"""Ready-made agents offered first in the Create agent dialog.

Each starter is a workflow with ``{{key}}`` placeholders plus the setup
questions that fill them, so a user only answers questions about their
business. ``python -m scripts.sync_agent_templates`` writes them to the
``workflow_templates`` table.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from api.schemas.workflow_template import TemplateSetupField
from api.services.workflow.agent_builder import (
    AgentSpec,
    CapturedFieldSpec,
    StageSpec,
    assemble_workflow_definition,
)
from api.services.workflow.template_setup import INTEGRATION_TOOL_PREFIX

GOOGLE_CALENDAR = "google-calendar"


@dataclass(frozen=True, slots=True)
class StarterTemplate:
    name: str
    description: str
    setup_fields: list[TemplateSetupField]
    definition: dict[str, Any]
    call_type: Literal["inbound", "outbound"]
    icon: str
    featured: bool = False
    integrations: list[str] = field(default_factory=list)

    def row(self) -> dict[str, Any]:
        """The workflow_templates columns for this starter."""
        return {
            "template_description": self.description,
            "template_json": self.definition,
            "setup_fields": [
                f.model_dump(exclude_none=True) for f in self.setup_fields
            ],
            "call_type": self.call_type,
            "icon": self.icon,
            "featured": self.featured,
            "integrations": self.integrations,
        }


def _with_integration_tools(
    definition: dict[str, Any], provider: str
) -> dict[str, Any]:
    """Mark every prompted step as able to use *provider*'s tool once the
    user connects it (see template_setup.attach_integration_tools)."""
    placeholder = INTEGRATION_TOOL_PREFIX + provider
    for node in definition["nodes"]:
        if node["type"] in ("startCall", "agentNode"):
            node["data"]["tool_uuids"] = [placeholder]
    return definition


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
            "else.\n\n"
            "If they want an appointment and you have calendar tools: check "
            "availability for the day they ask about, offer at most two or three "
            "times, and book the one they choose with their name and phone "
            "number. Confirm the day and time back to them. To cancel, look up "
            "and cancel their booking.\n\n"
            "If you have no calendar tools, or they need a callback or a person, "
            "explain that you will take a message for the team."
        ),
        done_when=(
            "The caller needs something you cannot do yourself, such as a "
            "callback, speaking to a person, or a booking you could not make."
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
        "The caller has what they need (for example their appointment is "
        "booked) and wants to go, says goodbye, or it is a wrong number or a "
        "sales call."
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
            "Answers every call, tells callers about your business, books "
            "appointments and takes messages."
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
        definition=_with_integration_tools(
            assemble_workflow_definition(_RECEPTIONIST, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="phone",
        featured=True,
        integrations=[GOOGLE_CALENDAR],
    ),
]
