"""Ready-made agents offered first in the Create agent wizard.

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

TemplateCategory = Literal[
    "general",
    "telephony",
    "clinic",
    "trades",
    "restaurant",
    "estate",
    "salon",
]


@dataclass(frozen=True, slots=True)
class StarterTemplate:
    name: str
    description: str
    setup_fields: list[TemplateSetupField]
    definition: dict[str, Any]
    call_type: Literal["inbound", "outbound"]
    icon: str
    category: TemplateCategory = "general"
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
            "category": self.category,
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


def _business_fields(
    *,
    name_placeholder: str,
    description_placeholder: str,
    hours_placeholder: str = "Mon–Fri 9am–6pm, Sat 10am–2pm, closed Sunday",
    address_placeholder: str = "12 Main Street, Dublin 2",
    website_placeholder: str = "https://example.ie",
    extra_help: str = "Parking, prices, payment options, languages you speak.",
    extra_placeholder: str = "Free parking behind the building. We take card and cash.",
    ask_address: bool = True,
) -> list[TemplateSetupField]:
    """The business questions a starter asks. Agents that never mention the
    address leave it out, so nobody types in an answer that goes unused."""
    head = [
        TemplateSetupField(
            key="business_name",
            label="Business name",
            placeholder=name_placeholder,
            max_length=120,
        ),
        TemplateSetupField(
            key="business_description",
            label="What does your business do?",
            type="textarea",
            placeholder=description_placeholder,
        ),
        TemplateSetupField(
            key="opening_hours",
            label="Opening hours",
            placeholder=hours_placeholder,
            max_length=300,
        ),
    ]
    address = (
        [
            TemplateSetupField(
                key="address",
                label="Address",
                placeholder=address_placeholder,
                required=False,
                max_length=300,
            )
        ]
        if ask_address
        else []
    )
    tail = [
        TemplateSetupField(
            key="website",
            label="Website",
            type="url",
            placeholder=website_placeholder,
            required=False,
            max_length=300,
        ),
        TemplateSetupField(
            key="extra_info",
            label="Anything else callers often ask?",
            type="textarea",
            help=extra_help,
            placeholder=extra_placeholder,
            required=False,
            max_length=1500,
        ),
    ]
    return [*head, *address, *tail]


def _message_stage() -> StageSpec:
    return StageSpec(
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


def _message_fields() -> list[CapturedFieldSpec]:
    return [
        CapturedFieldSpec(name="caller_name", description="The caller's name."),
        CapturedFieldSpec(
            name="callback_number", description="The best number to call them back on."
        ),
        CapturedFieldSpec(
            name="call_reason", description="Why they called, in one line."
        ),
    ]


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
    stages=[_message_stage()],
    closing_prompt=(
        "Tell the caller the team will get back to them during opening hours, "
        "thank them for calling {{business_name}}, and say goodbye."
    ),
    end_call_when=(
        "The caller has what they need (for example their appointment is "
        "booked) and wants to go, says goodbye, or it is a wrong number or a "
        "sales call."
    ),
    captured_fields=_message_fields(),
)

_CLINIC = AgentSpec(
    name="Clinic receptionist",
    persona=(
        "You are the calm, professional phone receptionist for "
        "{{business_name}}, a clinic. "
        "About the clinic: {{business_description}}\n\n"
        "Opening hours: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed. Offer to take a message instead.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other things patients often ask: {{extra_info | fallback:nothing else.}}\n\n"
        "Never give medical advice or diagnose. For anyone in severe pain or an "
        "emergency, tell them to call emergency services or go to A&E, then offer "
        "to take a message for reception."
    ),
    greeting=("Hello, thanks for calling {{business_name}}. How can I help you today?"),
    opening=StageSpec(
        name="Help the patient",
        prompt=(
            "Find out whether they want to book, move or cancel a visit, or ask "
            "about hours, location or services. Answer from the facts you have.\n\n"
            "If they want an appointment and you have calendar tools: check "
            "availability, offer two or three times, book with their name and "
            "phone number, and confirm the day and time.\n\n"
            "If you cannot help, or they need a person, take a message."
        ),
        done_when=(
            "The caller needs a callback, a person, or a booking you could not make."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Thank them for calling {{business_name}} and say a short goodbye."
    ),
    end_call_when=(
        "Their visit is booked or cancelled, they have the answer they need, "
        "they say goodbye, or it is a wrong number."
    ),
    captured_fields=_message_fields(),
)

_TRADES = AgentSpec(
    name="Trades after-hours",
    persona=(
        "You answer the phone for {{business_name}} when the team is on a job "
        "or after hours. "
        "About the business: {{business_description}}\n\n"
        "Usual hours: {{opening_hours}}\n"
        "Address or base: {{address | fallback:not listed.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other notes: {{extra_info | fallback:nothing else.}}\n\n"
        "Capture the job clearly so an engineer can call back. Ask whether "
        "there is any smell of gas or immediate danger; if yes, tell them to "
        "call emergency services first."
    ),
    greeting=(
        "Hi, you've reached {{business_name}}. The team may be on a job — "
        "I can take the details and get someone to ring you back. What's going on?"
    ),
    opening=StageSpec(
        name="Capture the job",
        prompt=(
            "Ask what the problem is, the address if they have one, and how "
            "urgent it feels. One question at a time. If they only want hours "
            "or a price range you know, answer briefly.\n\n"
            "Then take a message: name, best number, and a short summary of the job."
        ),
        done_when="You have enough for the team to call back, or they want to end.",
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Confirm someone from {{business_name}} will call them back, thank them, "
        "and say goodbye."
    ),
    end_call_when=(
        "You have the message, they say goodbye, or it is a wrong number or sales call."
    ),
    captured_fields=_message_fields(),
)

_RESTAURANT = AgentSpec(
    name="Restaurant bookings",
    persona=(
        "You take phone bookings for {{business_name}}. "
        "About the place: {{business_description}}\n\n"
        "Opening hours: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other notes (allergies, parking, dress code): "
        "{{extra_info | fallback:nothing else.}}\n\n"
        "Be warm and concise. Never invent availability you do not have tools for."
    ),
    greeting=(
        "Hello, {{business_name}}. Would you like to book a table, or can I help "
        "with something else?"
    ),
    opening=StageSpec(
        name="Take a booking or answer",
        prompt=(
            "If they want a table and you have calendar tools: ask for day, time "
            "and party size, check availability, book under their name and phone, "
            "and confirm.\n\n"
            "If you have no calendar tools, take a message with day, time, party "
            "size, name and number for the team.\n\n"
            "Answer simple questions about hours, location or notes from the facts "
            "you have."
        ),
        done_when=(
            "The booking is done, you have a message for the team, or they need a person."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Thank them for choosing {{business_name}} and say a short goodbye."
    ),
    end_call_when=(
        "The booking or message is done, they say goodbye, or it is a wrong number."
    ),
    captured_fields=_message_fields(),
)

_ESTATE = AgentSpec(
    name="Estate viewing booker",
    persona=(
        "You answer after-hours and busy-desk calls for {{business_name}}, an "
        "estate agency. "
        "About the agency: {{business_description}}\n\n"
        "Office hours: {{opening_hours}}\n"
        "Office address: {{address | fallback:not listed.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other notes: {{extra_info | fallback:nothing else.}}\n\n"
        "You can answer general questions and book viewings when tools allow. "
        "Never invent listing prices or say a property is sold unless that is "
        "in the facts you have."
    ),
    greeting=(
        "Hi, thanks for calling {{business_name}}. Are you looking to book a "
        "viewing, or can I help with something else?"
    ),
    opening=StageSpec(
        name="Help the caller",
        prompt=(
            "If they want a viewing and you have calendar tools: ask which "
            "property or area, offer times, book with name and mobile, and confirm.\n\n"
            "If you cannot book, take a message with their name, number, and which "
            "property they mean.\n\n"
            "Answer simple office-hour or location questions from your facts."
        ),
        done_when=(
            "A viewing is booked, a message is taken, or they need an agent to call back."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=("Thank them for calling {{business_name}} and say goodbye."),
    end_call_when=(
        "The viewing or message is done, they say goodbye, or it is a wrong number."
    ),
    captured_fields=_message_fields(),
)

_VOIP_LINE = AgentSpec(
    name="VoIP phone receptionist",
    persona=(
        "You answer the main VoIP / phone line for {{business_name}}. "
        "About the business: {{business_description}}\n\n"
        "Opening hours: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed. Offer to take a message instead.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other things callers often ask: {{extra_info | fallback:nothing else.}}\n\n"
        "Speak clearly for phone audio. Keep answers short. Never invent prices "
        "or availability: offer to take a message so the team can call back."
    ),
    greeting=("Hello, you've reached {{business_name}}. How can I help you today?"),
    opening=StageSpec(
        name="Route the call",
        prompt=(
            "Find out why they called. Answer simple questions from your facts.\n\n"
            "If they want an appointment and you have calendar tools: check "
            "availability, offer two or three times, book with name and number, "
            "and confirm.\n\n"
            "If they ask for a person, a department, or something you cannot do, "
            "take a clear message for the team."
        ),
        done_when=(
            "They need a callback, a person, or a booking you could not complete."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Thank them for calling {{business_name}} and say a short goodbye."
    ),
    end_call_when=(
        "They have what they need, say goodbye, or it is a wrong number or sales call."
    ),
    captured_fields=_message_fields(),
)

_SALON = AgentSpec(
    name="Salon receptionist",
    persona=(
        "You are the friendly phone receptionist for {{business_name}}, a salon "
        "or barbers. "
        "About the salon: {{business_description}}\n\n"
        "Opening hours: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other notes (prices, stylists, parking): "
        "{{extra_info | fallback:nothing else.}}\n\n"
        "Be warm and brief. Do not invent prices or free slots you cannot check."
    ),
    greeting=(
        "Hi, thanks for calling {{business_name}}. Would you like to book, or "
        "can I help with something else?"
    ),
    opening=StageSpec(
        name="Book or answer",
        prompt=(
            "If they want an appointment and you have calendar tools: ask what "
            "they need, check availability, book with name and mobile, and confirm.\n\n"
            "If you cannot book, take a message with service, preferred times, "
            "name and number.\n\n"
            "Answer short questions about hours, location or notes from your facts."
        ),
        done_when=(
            "The booking or message is done, or they need a person to call back."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=("Thank them for calling {{business_name}} and say goodbye."),
    end_call_when=(
        "The booking or message is done, they say goodbye, or it is a wrong number."
    ),
    captured_fields=_message_fields(),
)

_LEAD_FOLLOW_UP = AgentSpec(
    name="Lead follow-up",
    persona=(
        "You are calling on behalf of {{business_name}} to follow up a lead. "
        "About the business: {{business_description}}\n\n"
        "Usual hours for callbacks: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Extra context for the call: {{extra_info | fallback:nothing else.}}\n\n"
        "Be polite, short, and never pushy. If they are busy, offer a callback. "
        "If they are not interested, thank them and end cleanly."
    ),
    greeting=(
        "Hi, this is {{business_name}} calling. Have I caught you at an okay time "
        "for a quick follow-up?"
    ),
    opening=StageSpec(
        name="Qualify the lead",
        prompt=(
            "Confirm they still want help. Ask one or two short questions about "
            "what they need. Capture name, best number, and interest in one line.\n\n"
            "If they want a booked call or visit and you have calendar tools, "
            "offer times and book. Otherwise take a message for the team."
        ),
        done_when=(
            "You have interest details, a booking, a callback request, or a clear no."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Thank them for their time, say what happens next from {{business_name}}, "
        "and goodbye."
    ),
    end_call_when=(
        "They are not interested, the follow-up is done, they ask to stop, or "
        "it is a wrong number."
    ),
    captured_fields=_message_fields(),
)

_APPOINTMENT_REMINDER = AgentSpec(
    name="Appointment reminder",
    persona=(
        "You call customers for {{business_name}} to remind them of an upcoming "
        "appointment. "
        "About the business: {{business_description}}\n\n"
        "Opening hours: {{opening_hours}}\n"
        "Address: {{address | fallback:not listed.}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other notes: {{extra_info | fallback:nothing else.}}\n\n"
        "Keep the call under two minutes. Confirm, reschedule via calendar tools "
        "if you have them, or take a message."
    ),
    greeting=(
        "Hi, this is {{business_name}} with a quick reminder about your upcoming "
        "appointment. Is now a good time?"
    ),
    opening=StageSpec(
        name="Confirm the visit",
        prompt=(
            "Confirm they still plan to attend. If they need to move it and you "
            "have calendar tools: offer two or three new times, update the booking, "
            "and confirm.\n\n"
            "If they cancel or you cannot change the diary, take a short message "
            "for the team with their name and number."
        ),
        done_when=(
            "They confirmed, rescheduled, cancelled, or asked for a human callback."
        ),
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Thank them, remind them briefly where to go if useful, and say goodbye."
    ),
    end_call_when=(
        "Confirmation or change is done, they say goodbye, or it is a wrong number."
    ),
    captured_fields=_message_fields(),
)

_FEEDBACK = AgentSpec(
    name="Customer feedback",
    persona=(
        "You call recent customers of {{business_name}} to ask how things went. "
        "About the business: {{business_description}}\n\n"
        "Hours: {{opening_hours}}\n"
        "Website: {{website | fallback:not listed.}}\n"
        "Other notes: {{extra_info | fallback:nothing else.}}\n\n"
        "Be warm and brief. Ask for a 1–5 score and one sentence of feedback. "
        "Never argue about a complaint — thank them and note it for the team."
    ),
    greeting=(
        "Hi, this is {{business_name}}. We're checking in after your recent visit "
        "— have you got a minute for two quick questions?"
    ),
    opening=StageSpec(
        name="Collect feedback",
        prompt=(
            "Ask how it went overall, then a score from 1 to 5, then one thing "
            "that went well or could improve. Capture name if they give it, the "
            "score, and the comment.\n\n"
            "If they are unhappy and want a callback, take a message for the team."
        ),
        done_when="You have a score and a short comment, or they decline.",
    ),
    stages=[_message_stage()],
    closing_prompt=(
        "Thank them for the feedback on behalf of {{business_name}} and say goodbye."
    ),
    end_call_when=(
        "Feedback is captured, they decline, they say goodbye, or it is a wrong number."
    ),
    captured_fields=[
        CapturedFieldSpec(
            name="caller_name", description="The customer's name if given."
        ),
        CapturedFieldSpec(
            name="callback_number", description="Best number if they want a callback."
        ),
        CapturedFieldSpec(
            name="satisfaction_score", description="Score from 1 to 5 if given."
        ),
        CapturedFieldSpec(
            name="call_reason", description="Their feedback in one line."
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
        setup_fields=_business_fields(
            name_placeholder="Bloom Dental",
            description_placeholder=(
                "Family dental practice in Dublin. Check-ups, cleaning, "
                "whitening and emergency appointments."
            ),
            website_placeholder="https://bloomdental.ie",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_RECEPTIONIST, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="phone",
        category="general",
        featured=True,
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Clinic receptionist",
        description=(
            "Books and moves clinic visits, answers hours and location, and "
            "passes anyone in pain to reception."
        ),
        setup_fields=_business_fields(
            name_placeholder="River Physio",
            description_placeholder=(
                "Physiotherapy clinic in Cork. Sports injuries, back pain and "
                "post-op rehab."
            ),
            website_placeholder="https://riverphysio.ie",
            extra_help="Insurance, first-visit notes, parking.",
            extra_placeholder="New patients please arrive 10 minutes early. Free street parking nearby.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_CLINIC, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="activity",
        category="clinic",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Trades after-hours",
        description=(
            "Takes job details when you are on site, flags emergencies, and "
            "books a call-back."
        ),
        setup_fields=_business_fields(
            name_placeholder="Murphy Plumbing",
            description_placeholder=(
                "Emergency and planned plumbing across Limerick. Boilers, leaks "
                "and bathroom installs."
            ),
            hours_placeholder="Mon–Fri 8am–6pm; emergency call-outs evenings and weekends",
            website_placeholder="https://murphyplumbing.ie",
            extra_help="Areas you cover, call-out fees if you publish them.",
            extra_placeholder="We cover Limerick city and county. Standard call-out from €80.",
        ),
        definition=assemble_workflow_definition(_TRADES, "INBOUND"),
        call_type="inbound",
        icon="moon",
        category="trades",
    ),
    StarterTemplate(
        name="Restaurant bookings",
        description=(
            "Takes table bookings and answers the usual questions while the "
            "floor is busy."
        ),
        setup_fields=_business_fields(
            name_placeholder="Harbour Kitchen",
            description_placeholder=(
                "Casual seafood restaurant in Galway. Lunch and dinner, groups welcome."
            ),
            hours_placeholder="Tue–Sun 12–3pm and 5–10pm, closed Monday",
            website_placeholder="https://harbourkitchen.ie",
            extra_help="Allergies, terrace, kids, parking.",
            extra_placeholder="Please tell us about allergies when you book. High chairs available.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_RESTAURANT, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="utensils",
        category="restaurant",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Estate viewing booker",
        description=(
            "Answers listing questions after hours and books viewings into your diary."
        ),
        setup_fields=_business_fields(
            name_placeholder="Shannon Homes",
            description_placeholder=(
                "Residential sales and lettings across Clare and Limerick."
            ),
            hours_placeholder="Mon–Fri 9am–5.30pm, Sat viewings by appointment",
            website_placeholder="https://shannonhomes.ie",
            extra_help="Areas, sales vs lettings, viewing rules.",
            extra_placeholder="Bring photo ID to viewings. Pets policy depends on the landlord.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_ESTATE, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="star",
        category="estate",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="VoIP phone receptionist",
        description=(
            "Answers your main VoIP or phone line: answers FAQs, takes "
            "messages, and can book into your calendar."
        ),
        setup_fields=_business_fields(
            name_placeholder="Connolly & Co",
            description_placeholder=(
                "Accountants in Dublin. Bookkeeping, payroll and company returns "
                "for SMEs."
            ),
            website_placeholder="https://connollyco.ie",
            extra_help="Departments, after-hours policy, languages.",
            extra_placeholder="Ask for accounts or payroll. Irish and English spoken.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_VOIP_LINE, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="phone-incoming",
        category="telephony",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Salon receptionist",
        description=(
            "Books cuts and colour, answers hours and prices, and takes messages "
            "when the chair is busy."
        ),
        setup_fields=_business_fields(
            name_placeholder="Harbour Cuts",
            description_placeholder=(
                "Unisex salon in Howth. Cuts, colour and blow-drys."
            ),
            hours_placeholder="Tue–Sat 9am–6pm, closed Sunday and Monday",
            website_placeholder="https://harbourcuts.ie",
            extra_help="Stylists, deposit policy, parking.",
            extra_placeholder="Walk-ins welcome if free. Card only.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_SALON, "INBOUND"), GOOGLE_CALENDAR
        ),
        call_type="inbound",
        icon="scissors",
        category="salon",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Lead follow-up",
        description=(
            "Calls new leads, checks interest, and books a callback or meeting "
            "when you are ready."
        ),
        setup_fields=_business_fields(
            name_placeholder="GreenRoof Solar",
            description_placeholder=(
                "Residential solar quotes across Ireland. Free roof surveys."
            ),
            hours_placeholder="Mon–Fri 9am–6pm for survey bookings",
            website_placeholder="https://greenroof.ie",
            address_placeholder="Unit 4, Clondalkin Business Park, Dublin 22",
            extra_help="What the lead asked for, offer, or campaign name.",
            extra_placeholder="They requested a quote from the website form this week.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_LEAD_FOLLOW_UP, "OUTBOUND"), GOOGLE_CALENDAR
        ),
        call_type="outbound",
        icon="phone-outgoing",
        category="telephony",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Appointment reminder",
        description=(
            "Calls ahead of a visit to confirm, reschedule, or cancel so you "
            "lose fewer no-shows."
        ),
        setup_fields=_business_fields(
            name_placeholder="Bright Smile Dental",
            description_placeholder=(
                "Family dental clinic in Galway. Check-ups and hygiene."
            ),
            website_placeholder="https://brightsmile.ie",
            extra_help="What to bring, parking, late policy.",
            extra_placeholder="Please arrive 5 minutes early. Free parking at the rear.",
        ),
        definition=_with_integration_tools(
            assemble_workflow_definition(_APPOINTMENT_REMINDER, "OUTBOUND"),
            GOOGLE_CALENDAR,
        ),
        call_type="outbound",
        icon="bell",
        category="telephony",
        integrations=[GOOGLE_CALENDAR],
    ),
    StarterTemplate(
        name="Customer feedback",
        description=(
            "Short outbound calls for a 1–5 score and one comment after a visit or job."
        ),
        setup_fields=_business_fields(
            name_placeholder="Oak & Ember",
            description_placeholder=(
                "Neighbourhood café in Cork. Breakfast, lunch and takeaway."
            ),
            hours_placeholder="Mon–Sat 8am–4pm, closed Sunday",
            website_placeholder="https://oakandember.ie",
            extra_help="What they bought or which visit to ask about.",
            extra_placeholder="They ordered lunch with us earlier this week.",
            ask_address=False,
        ),
        definition=assemble_workflow_definition(_FEEDBACK, "OUTBOUND"),
        call_type="outbound",
        icon="message",
        category="general",
    ),
]
