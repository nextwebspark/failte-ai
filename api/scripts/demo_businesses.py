"""The four invented businesses behind the demo accounts, and the calls they get.

Used by ``api.scripts.seed_demo_accounts``. Everything here is made up: the
businesses, their people, their callers and the numbers (all in the 555
range, never dialled). Each call is a scripted conversation; the seed turns it
into the stored shape a real inbound phone call has.

A scenario is a function of a ``Ctx`` (the call's own random generator, its
caller and its local start time) that returns a ``Plan``: what was said, what
the agent wrote down, the outcome and the call review that matches it.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from api.schemas.opening_hours import OpeningHours, OpenRange

# --- what a call is made of -------------------------------------------------


@dataclass
class Step:
    # "agent" | "caller" | "move" | "tool" | "transfer"
    kind: str
    text: str = ""
    # move: the node the agent goes to and the function it calls to get there
    target: str = ""
    function: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    # tool: what the tool answered (a calendar tool's JSON object)
    result: Any = None
    # transfer: whether the person picked up
    answered: bool = True
    # transfer: skipped because the business was closed (the live gate's
    # "closed" result; nobody was rung)
    closed: bool = False


@dataclass
class Plan:
    steps: list[Step]
    outcome: str
    captured: dict[str, str]
    summary: str
    reason: str
    unanswered: list[str] = field(default_factory=list)
    time_was_full: bool = False
    # The call review's special-request tags (restaurants: see
    # ``call_review.categories.RESTAURANT_REQUEST_TAGS``), as said on the call.
    request_tags: list[str] = field(default_factory=list)
    # end_call | transfer_call | user_hangup
    status: str = "end_call"
    speech: bool = True
    # A silent caller stays on the line this long after the greeting.
    silence_seconds: float = 0.0
    # The call review's caller_language (ISO 639-1): what the caller spoke.
    caller_language: str = "en"
    # The call review's emergency flag: sent to 112/999.
    emergency: bool = False
    # The caller's voice when it isn't the pooled caller's (a caller speaking
    # another language): a Chirp 3 HD voice name.
    caller_voice: str | None = None


# Outcomes (the result the dashboard reads from the stored call).
HANDLED = "handled"
BOOKING_MADE = "booking_made"
CALLBACK = "callback_requested"
TRANSFERRED = "transferred"
TRANSFER_NOT_ANSWERED = "transfer_not_answered"
SILENT = "hung_up_silent"
TIME_WAS_FULL = "time_was_full"
UNANSWERED = "unanswered_question"

CHECK_FN = "mcp__google_calendar__check_appointment_availability"
BOOK_FN = "mcp__google_calendar__book_appointment"


@dataclass(frozen=True)
class Caller:
    first: str
    surname: str
    number: str | None
    female: bool

    @property
    def name(self) -> str:
        return f"{self.first} {self.surname}"


@dataclass
class Ctx:
    rng: random.Random
    caller: Caller
    started: datetime  # local time
    business: Business
    # What the agent says first: the disclosure and its greeting.
    greeting: str

    def pick(self, options):
        return self.rng.choice(options)

    def number_words(self) -> str:
        """The caller's number as they would say it: "085 555 0142"."""
        digits = (self.caller.number or "+353855550100").replace("+353", "0")
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"

    def number_digits(self) -> str:
        """The number as the agent writes it down: the caller's own, as the
        carrier sent it, so the follow-up doesn't list it twice."""
        return self.caller.number or "+353855550100"

    def day(self, *, closed: tuple[int, ...] = (), soon: bool = True):
        """A day the caller asks about: (spoken, ISO date, weekday name)."""
        today = self.started.date()
        options = []
        for ahead in range(0 if soon else 1, 7):
            when = today + timedelta(days=ahead)
            if when.weekday() in closed:
                continue
            options.append((ahead, when))
        ahead, when = self.rng.choice(options[:5])
        name = when.strftime("%A")
        if ahead == 0:
            spoken = "tonight" if self.business.kind == "restaurant" else "today"
        elif ahead == 1:
            spoken = "tomorrow"
        else:
            spoken = f"on {name}"
        return spoken, when.isoformat(), name


# Times as people say them, and as the agent writes them down.
EVENING_TIMES = [
    ("half six", "18:30", "6:30 pm"),
    ("seven", "19:00", "7:00 pm"),
    ("half seven", "19:30", "7:30 pm"),
    ("eight", "20:00", "8:00 pm"),
    ("quarter to eight", "19:45", "7:45 pm"),
]
LUNCH_TIMES = [
    ("half twelve", "12:30", "12:30 pm"),
    ("one", "13:00", "1:00 pm"),
    ("half one", "13:30", "1:30 pm"),
]
DAY_TIMES = [
    ("nine", "09:00", "9:00 am"),
    ("half ten", "10:30", "10:30 am"),
    ("eleven", "11:00", "11:00 am"),
    ("two", "14:00", "2:00 pm"),
    ("half three", "15:30", "3:30 pm"),
    ("four", "16:00", "4:00 pm"),
]
NUMBERS = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    10: "ten",
    12: "twelve",
    14: "fourteen",
    16: "sixteen",
}


def _slot(on: str, hhmm: str) -> str:
    """A calendar slot id: the slot's ISO time in Irish winter time."""
    return f"{on}T{hhmm}:00+00:00"


class Talk:
    """Builds a Plan's steps. The agent starts on the opening step."""

    def __init__(self, greeting: str):
        self.steps: list[Step] = [Step("agent", greeting)]
        self.node = "start"

    def a(self, text: str) -> Talk:
        self.steps.append(Step("agent", text))
        return self

    def c(self, text: str) -> Talk:
        self.steps.append(Step("caller", text))
        return self

    def message(self) -> Talk:
        """On to the "Take a message" step."""
        self.steps.append(
            Step("move", target="stage_1", function="go_to_take_a_message")
        )
        self.node = "stage_1"
        return self

    def tool(self, function: str, arguments: dict, result: dict) -> Talk:
        self.steps.append(
            Step("tool", function=function, arguments=arguments, result=result)
        )
        return self

    def transfer(self, answered: bool) -> Talk:
        self.steps.append(Step("transfer", answered=answered))
        return self

    def bye(self, closing: str) -> Talk:
        if self.node == "stage_1":
            self.steps.append(Step("move", target="end", function="finish_call"))
        else:
            self.steps.append(Step("move", target="end_early", function="end_call"))
        self.steps.append(Step("agent", closing))
        return self


# --- the businesses ----------------------------------------------------------


@dataclass
class BusyCall:
    """A caller who rang while every line was busy (the calls-at-once
    limit), on the most recent ``weekday`` at ``at``. ``message`` is the
    voicemail they left; None: they hung up without leaving one."""

    weekday: int  # Monday is 0
    at: str  # "20:10", local time
    message: str | None = None


@dataclass
class Business:
    slug: str
    name: str
    kind: str  # restaurant | telecoms | dental | trades
    template_name: str
    facts: dict[str, str]
    owner_name: str
    staff_name: str
    called_number: str
    # Calls on an ordinary day, by weekday (Monday first).
    daily_calls: tuple[float, ...]
    # Relative weight of each local hour 0-23.
    hours: tuple[float, ...]
    scenarios: list[tuple[float, Callable[[Ctx], Plan]]]
    callers: list[Caller]
    # Days the business never takes bookings for.
    closed_days: tuple[int, ...] = ()
    # The opening hours as times (the same hours as the ``opening_hours``
    # text above); the seed saves them on the agent.
    opening_hours: OpeningHours | None = None
    # Calls that are always this scenario, by index (0 is the newest call),
    # so the history always shows them; every other call is drawn by weight.
    pinned: dict[int, Callable[[Ctx], Plan]] = field(default_factory=dict)
    # Callers turned away because every line was busy ("Lines were busy").
    lines_busy: tuple[BusyCall, ...] = ()


def _week(
    *days: tuple[tuple[str, str], ...],
    note: str | None = None,
    transfer_only_when_open: bool = True,
) -> OpeningHours:
    """Opening hours from seven days (Monday first) of (open, close) pairs."""
    return OpeningHours(
        days=tuple(tuple(OpenRange(open=o, close=c) for o, c in day) for day in days),
        note=note,
        transfer_only_when_open=transfer_only_when_open,
    )


def _hours(**weights: float) -> tuple[float, ...]:
    """Hour weights from ``h9=3, h10=4`` style keywords (default 0)."""
    values = [0.0] * 24
    for key, weight in weights.items():
        values[int(key[1:])] = weight
    return tuple(values)


def _callers(seed: str, numbers_prefix: str, count: int) -> list[Caller]:
    rng = random.Random(f"callers:{seed}")
    women = [
        "Aoife",
        "Siobhán",
        "Niamh",
        "Ciara",
        "Gráinne",
        "Orla",
        "Sinéad",
        "Róisín",
        "Emma",
        "Sarah",
        "Mary",
        "Deirdre",
        "Caoimhe",
        "Laura",
        "Eimear",
        "Clodagh",
        "Maeve",
        "Fiona",
        "Áine",
        "Rachel",
    ]
    men = [
        "Seán",
        "Conor",
        "Pádraig",
        "Darragh",
        "Cian",
        "Eoin",
        "Liam",
        "Declan",
        "Brian",
        "Fergal",
        "Colm",
        "Donal",
        "Shane",
        "Tadhg",
        "Kevin",
        "Ronan",
        "Mark",
        "Barry",
        "Diarmuid",
        "Niall",
    ]
    surnames = [
        "Murphy",
        "Kelly",
        "O'Sullivan",
        "Walsh",
        "O'Brien",
        "Byrne",
        "Ryan",
        "O'Connor",
        "O'Neill",
        "Doyle",
        "McCarthy",
        "Gallagher",
        "Kennedy",
        "Lynch",
        "Murray",
        "Quinn",
        "Moore",
        "McLoughlin",
        "Carroll",
        "Connolly",
        "Daly",
        "Brennan",
        "Burke",
        "Collins",
        "Fitzgerald",
        "Hayes",
        "Nolan",
        "Power",
        "Hogan",
        "Cullen",
    ]
    callers: list[Caller] = []
    used: set[str] = set()
    while len(callers) < count:
        female = rng.random() < 0.52
        first = rng.choice(women if female else men)
        surname = rng.choice(surnames)
        if f"{first} {surname}" in used:
            continue
        used.add(f"{first} {surname}")
        index = len(callers)
        # 555 numbers: fictitious, never dialled. About one in fifteen
        # callers withholds their number.
        number = (
            None
            if rng.random() < 0.066
            else f"+353{numbers_prefix[index % len(numbers_prefix)]}555{index + 101:04d}"
        )
        callers.append(Caller(first, surname, number, female))
    return callers


# --- Linen Quay Kitchen: a restaurant in Galway ---------------------------------

RESTAURANT_NAME = "Linen Quay Kitchen"


def _r_book(c: Ctx) -> Plan:
    spoken, on, weekday = c.day(closed=(0,))
    lunch = c.rng.random() < 0.25
    say, hhmm, written = c.pick(LUNCH_TIMES if lunch else EVENING_TIMES)
    size = c.pick([2, 2, 2, 3, 4, 4, 5, 6])
    allergy = c.pick([None, None, None, "a coeliac", "a nut allergy", "dairy-free"])
    occasion = c.pick([None, None, None, "a birthday", "an anniversary"])
    # The agent asks about one or the other, never both.
    if allergy:
        occasion = None
    # (what the caller asks for, how the booking notes it, the review's tag)
    extra_ask = c.pick(
        [
            None,
            None,
            None,
            None,
            None,
            ("Could we have a high chair for the little one?", "a high chair", "kids"),
            ("Any chance of a table on the terrace?", "a terrace table", "seating"),
            ("Could we have a table by the window?", "a window table", "seating"),
            (
                "My mother uses a wheelchair, is it step-free?",
                "step-free access for a wheelchair",
                "accessibility",
            ),
        ]
    )
    part = "lunch" if lunch else "evening"
    t = Talk(c.greeting)
    t.c(f"Hi, could I book a table for {NUMBERS[size]} {spoken}, around {say}?")
    t.tool(
        CHECK_FN,
        {
            "relative_day": spoken.replace("on ", "").lower(),
            "part_of_day": part,
            "party_size": size,
        },
        {
            "slots": [{"id": _slot(on, hhmm), "say": f"{weekday} at {say}"}],
            "say": f"I have {weekday} at {say} for {NUMBERS[size]}.",
        },
    )
    t.a(
        f"Yes, I have {say} {spoken} for {NUMBERS[size]}. Can I take a name for the booking?"
    )
    t.c(f"It's {c.caller.surname}. {c.caller.name}.")
    t.a("Thanks. And a mobile number in case we need to reach you?")
    t.c(f"{c.number_words()}.")
    if allergy:
        t.a("Lovely. Any allergies or dietary needs we should know about?")
        t.c(f"One of us is {allergy}, if that's okay.")
        t.a(
            "That's no problem, the kitchen will look after them. I'll put it on the booking."
        )
    elif occasion:
        t.a("Lovely. Is it for a special occasion?")
        t.c(f"It's {occasion}, actually.")
        t.a("How nice. I'll add that to the booking.")
    if extra_ask:
        ask, noted, _ = extra_ask
        t.c(ask)
        t.a(f"Of course. I've noted {noted} on the booking.")
    t.a(
        f"So that's a table for {NUMBERS[size]} {spoken} at {say}, under {c.caller.name}. Shall I book that?"
    )
    t.c("Yes please.")
    t.tool(
        BOOK_FN,
        {
            "slot_id": _slot(on, hhmm),
            "caller_name": c.caller.name,
            "caller_phone": c.number_digits(),
            "party_size": size,
            "reason": allergy or occasion,
        },
        {
            "booked": True,
            "event_id": f"demo{c.rng.getrandbits(40):010x}",
            "say": f"That is booked in for {weekday} at {say}.",
            "starts_at": _slot(on, hhmm),
        },
    )
    t.a(f"You're booked in for {weekday} at {say}. We'll see you then.")
    t.c("Brilliant, thanks a million.")
    t.bye(f"Thanks for choosing {RESTAURANT_NAME}. Bye now.")
    extra = (
        f" Noted {allergy}."
        if allergy
        else f" It's for {occasion}."
        if occasion
        else ""
    )
    if extra_ask:
        extra += f" Asked for {extra_ask[1]}."
    requests = [r for r in (allergy, occasion, extra_ask and extra_ask[1]) if r]
    tags = [
        tag
        for tag, wanted in (
            ("allergies_diets", allergy),
            ("celebration", occasion),
            ("kids", extra_ask and extra_ask[2] == "kids"),
            ("accessibility", extra_ask and extra_ask[2] == "accessibility"),
            ("seating", extra_ask and extra_ask[2] == "seating"),
        )
        if wanted
    ]
    return Plan(
        t.steps,
        BOOKING_MADE,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Table for {size}",
            "booking_outcome": "booked",
            "booking_date": on,
            "booking_time": hhmm,
            "party_size": str(size),
            "special_requests": ", ".join(requests),
        },
        f"Booked a table for {size} {spoken} at {written}.{extra}",
        "reservations",
        request_tags=tags,
    )


def _r_full(c: Ctx) -> Plan:
    spoken, on, weekday = c.day(closed=(0,))
    size = c.pick([4, 5, 6, 6, 8])
    t = Talk(c.greeting)
    t.c(f"Hello, have you anything for {NUMBERS[size]} {spoken} at eight?")
    t.tool(
        CHECK_FN,
        {
            "relative_day": spoken.replace("on ", "").lower(),
            "part_of_day": "evening",
            "party_size": size,
        },
        {
            "slots": [
                {"id": _slot(on, "18:00"), "say": f"{weekday} at six"},
                {"id": _slot(on, "21:15"), "say": f"{weekday} at quarter past nine"},
            ],
            "say": f"Eight is full. I have six or quarter past nine on {weekday}.",
        },
    )
    t.a(
        f"I'm sorry, eight o'clock is full {spoken}. I could do six, or quarter past nine. Would either of those suit?"
    )
    keep = c.rng.random() < 0.5
    if keep:
        t.c("Ah no, six is too early for us. Could someone ring me if eight frees up?")
        t.a("Of course. I'll take your details for the team.")
        t.message()
        t.a("Can I have your name, please?")
        t.c(c.caller.name)
        t.a("And the best number to reach you?")
        t.c(c.number_words())
        t.a(f"That's {c.number_words()}. Is that right?")
        t.c("That's it.")
        t.a(
            f"Thanks, {c.caller.first}. The team will ring you if a table for {NUMBERS[size]} at eight comes free."
        )
        t.bye(f"Thanks for calling {RESTAURANT_NAME}. Goodbye.")
        captured = {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Wants 8:00 pm for {size}; call if a table frees up",
            "booking_outcome": "requested",
            "booking_date": on,
            "booking_time": "20:00",
            "party_size": str(size),
        }
        summary = (
            f"Wanted a table for {size} {spoken} at 8:00 pm, which was full. "
            "Asked to be rung if one frees up."
        )
        outcome = CALLBACK
    else:
        t.c("No, leave it so. We'll try another night. Thanks.")
        t.bye(f"No problem. Thanks for calling {RESTAURANT_NAME}. Bye.")
        captured = {
            "call_reason": f"Wanted 8:00 pm for {size}, full",
            "booking_date": on,
            "booking_time": "20:00",
            "party_size": str(size),
        }
        summary = (
            f"Wanted a table for {size} {spoken} at 8:00 pm, which was full. "
            "Turned down 6:00 pm and 9:15 pm."
        )
        outcome = TIME_WAS_FULL
    return Plan(t.steps, outcome, captured, summary, "reservations", time_was_full=True)


def _r_group(c: Ctx) -> Plan:
    spoken, on, _ = c.day(closed=(0,), soon=False)
    size = c.pick([10, 12, 14, 16])
    occasion = c.pick(
        ["a fortieth birthday", "a work Christmas party", "a christening"]
    )
    t = Talk(c.greeting)
    t.c(
        f"Hi, I'm looking to book for {NUMBERS[size]} people {spoken}, it's for {occasion}."
    )
    t.a(
        "Lovely. Groups of more than eight are booked by the team directly, so I'll take your details and they'll ring you to confirm."
    )
    t.message()
    t.a("Can I have your name?")
    t.c(c.caller.name)
    t.a("And the best number for you?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. And roughly what time were you thinking?")
    t.c("Around half seven if possible.")
    t.a(
        f"Perfect. I've noted {NUMBERS[size]} people {spoken} at half seven for {occasion}. The team will call you back today."
    )
    t.c("Great, thank you.")
    t.bye(f"Thanks for choosing {RESTAURANT_NAME}. Goodbye.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Group booking for {size}, {occasion}",
            "booking_outcome": "requested",
            "booking_date": on,
            "booking_time": "19:30",
            "party_size": str(size),
            "special_requests": occasion,
        },
        f"Asked for a table for {size} {spoken} at 7:30 pm for {occasion}. "
        "Left a number for the team to confirm.",
        "reservations",
        request_tags=["celebration"],
    )


def _r_hours(c: Ctx) -> Plan:
    question, answer, summary = c.pick(
        [
            (
                "Are you open on Mondays?",
                "We're closed on Mondays. We're open Tuesday to Thursday from twelve to three and five to half nine, and later on Friday and Saturday.",
                "Asked if you're open on Monday. Told closed Mondays and the usual hours.",
            ),
            (
                "What time do you close on a Sunday?",
                "On Sunday we're open from twelve until eight in the evening.",
                "Asked about Sunday hours. Told 12 to 8:00 pm.",
            ),
            (
                "What time does the kitchen close tonight?",
                "On Friday and Saturday we serve until half ten, and until half nine the rest of the week.",
                "Asked when the kitchen closes. Told 10:30 pm Friday and Saturday, 9:30 pm other nights.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi there, quick question. {question}")
    t.a(answer)
    t.c("Grand, that's all I needed. Thanks.")
    t.bye(f"You're welcome. Thanks for calling {RESTAURANT_NAME}.")
    return Plan(
        t.steps,
        HANDLED,
        {"call_reason": "Opening hours"},
        summary,
        "questions",
    )


def _r_question(c: Ctx) -> Plan:
    question, answer, summary = c.pick(
        [
            (
                "Do you have gluten-free options? My daughter is coeliac.",
                "Yes, there are gluten-free options on every menu. Just tell us when you book, or let your server know, and the kitchen will look after her.",
                "Asked about gluten-free food for a coeliac. Told there are options on every menu.",
            ),
            (
                "Is there parking near you?",
                "There's pay and display parking on the quay right outside, and it's free after six in the evening.",
                "Asked about parking. Told pay and display on the quay, free after 6:00 pm.",
            ),
            (
                "Can we bring the dog?",
                "Dogs are very welcome on the terrace, just not inside, I'm afraid.",
                "Asked if dogs are allowed. Told yes on the terrace.",
            ),
            (
                "Do you have high chairs?",
                "We do, yes. If you mention it when you book we'll have one ready.",
                "Asked about high chairs. Told yes.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(answer)
    t.c("Perfect, thanks very much.")
    t.bye(f"Not at all. Thanks for calling {RESTAURANT_NAME}. Bye.")
    return Plan(t.steps, HANDLED, {"call_reason": question[:60]}, summary, "questions")


def _r_takeaway(c: Ctx) -> Plan:
    count = c.pick([2, 3, 4])
    t = Talk(c.greeting)
    t.c(f"Hi, can I order {NUMBERS[count]} fish and chips to collect around seven?")
    t.a(
        "I can take that down for the kitchen. They'll ring you back to confirm the order and the time."
    )
    t.message()
    t.a("What name is it under?")
    t.c(c.caller.first)
    t.a("And a number for you?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. Correct?")
    t.c("Yes.")
    t.a(
        f"Thanks, {c.caller.first}. That's {NUMBERS[count]} fish and chips for around seven. Collection is at the side hatch on the quay."
    )
    t.bye(f"Thanks for choosing {RESTAURANT_NAME}. See you later.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Takeaway: {count} fish and chips to collect at 7:00 pm",
        },
        f"Ordered {count} fish and chips to collect at 7:00 pm. Waiting for the kitchen to confirm.",
        "takeaway",
    )


def _r_unanswered(c: Ctx) -> Plan:
    question, short = c.pick(
        [
            (
                "Do you have a private room for about twenty people?",
                "Do you have a private room for 20?",
            ),
            ("Is the terrace heated in the evenings?", "Is the terrace heated?"),
            (
                "Do you do a vegan option for the Sunday roast?",
                "Is there a vegan Sunday roast?",
            ),
            ("Do you sell gift vouchers?", "Do you sell gift vouchers?"),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(
        "I'm sorry, I don't have that information. I can take a message and someone from the team will get back to you."
    )
    t.c("Ah no, it's fine, I'll check the website. Thanks.")
    t.bye(f"No problem. Thanks for calling {RESTAURANT_NAME}.")
    return Plan(
        t.steps,
        UNANSWERED,
        {"call_reason": short},
        f"Asked: {short.lower().rstrip('?')}? Didn't get an answer and didn't leave a number.",
        "questions",
        unanswered=[short],
    )


def _r_change(c: Ctx) -> Plan:
    spoken, on, _ = c.day(closed=(0,))
    t = Talk(c.greeting)
    t.c(
        f"Hi, I've a booking {spoken} at seven under {c.caller.surname}. Could we push it to eight?"
    )
    t.a(
        "I'll pass that to the team so they can move it for you. Let me take your details."
    )
    t.message()
    t.a("Can I take your full name?")
    t.c(c.caller.name)
    t.a("And the best number to reach you?")
    t.c(c.number_words())
    t.a(
        f"Thanks. That's {c.number_words()}. The team will call to confirm the new time."
    )
    t.bye(f"Thanks for calling {RESTAURANT_NAME}. Bye.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": "Move booking from 7:00 pm to 8:00 pm",
            "booking_date": on,
            "booking_time": "20:00",
        },
        f"Asked to move a booking {spoken} from 7:00 pm to 8:00 pm. The team needs to confirm.",
        "changes",
    )


def _r_manager(c: Ctx, answered: bool) -> Plan:
    topic = c.pick(
        [
            ("I left my jacket there last night", "Left a jacket in the restaurant"),
            (
                "I want to talk to someone about a function next month",
                "Function next month",
            ),
            (
                "I'm calling from a supplier about tomorrow's delivery",
                "Supplier delivery",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi, it's {c.caller.name}. Could I speak to the manager? {topic[0]}.")
    t.a("Of course. One moment, I'm putting you through.")
    t.transfer(answered)
    if answered:
        return Plan(
            t.steps,
            TRANSFERRED,
            {"caller_name": c.caller.name, "call_reason": topic[1]},
            f"Asked for the manager: {topic[1].lower()}. Put through to the team.",
            "other",
            status="transfer_call",
        )
    t.a(
        "I'm sorry, nobody is free to pick up just now. Can I take a message for the manager?"
    )
    t.c("Yeah, go on.")
    t.message()
    t.a("What's your name?")
    t.c(c.caller.name)
    t.a("And your number?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. I'll make sure the manager gets this today.")
    t.bye(f"Thanks for calling {RESTAURANT_NAME}.")
    return Plan(
        t.steps,
        TRANSFER_NOT_ANSWERED,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": topic[1],
        },
        f"Asked for the manager: {topic[1].lower()}. Nobody picked up; left a number.",
        "other",
    )


def _r_polish(c: Ctx) -> Plan:
    """A caller who speaks Polish: the agent speaks English only, so it says
    one line in Polish offering staff or a call back, then takes the number
    in English."""
    name = "Agnieszka Kowalska"
    t = Talk(c.greeting)
    t.c(
        "Dzień dobry, chciałabym zarezerwować stolik dla czterech osób na "
        "sobotę wieczorem."
    )
    t.a(
        "Przepraszam, mogę pomóc tylko po angielsku. Mogę połączyć Panią z "
        "pracownikiem albo wziąć numer, żeby ktoś oddzwonił."
    )
    t.c("Call back, please. My English is not so good.")
    t.message()
    t.a("Of course. What's your name?")
    t.c(name)
    t.a("And the best number for you?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. Someone from the team will call you back.")
    t.bye(f"Thank you for calling {RESTAURANT_NAME}. Goodbye.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": name,
            "callback_number": c.number_digits(),
            "call_reason": "Table for 4 on Saturday evening (spoke Polish)",
        },
        "Asked in Polish about a table for 4 on Saturday evening. Was offered a "
        "call back and left a number.",
        "reservations",
        caller_language="pl",
        caller_voice="pl-PL-Chirp3-HD-Kore",
    )


def _silent(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    return Plan(
        t.steps,
        SILENT,
        {},
        "Hung up without speaking.",
        "other",
        status="user_hangup",
        speech=False,
        silence_seconds=c.rng.uniform(2.5, 7.0),
    )


RESTAURANT = Business(
    slug="linen-quay",
    name=RESTAURANT_NAME,
    kind="restaurant",
    template_name="Restaurant bookings",
    # The Saturday dinner rush: every line busy twice in a few minutes.
    lines_busy=(
        BusyCall(
            5,
            "20:12",
            "Hi, it's {first} here. I was hoping to book a table for four "
            "tomorrow evening, around seven if you have it. Could you ring me "
            "back on {number}? Thanks a million.",
        ),
        BusyCall(5, "20:16"),
    ),
    opening_hours=_week(
        (),
        (("12:00", "15:00"), ("17:00", "21:30")),
        (("12:00", "15:00"), ("17:00", "21:30")),
        (("12:00", "15:00"), ("17:00", "21:30")),
        (("12:00", "15:00"), ("17:00", "22:30")),
        (("12:00", "15:00"), ("17:00", "22:30")),
        (("12:00", "20:00"),),
    ),
    facts={
        "business_name": RESTAURANT_NAME,
        "business_description": (
            "Seafood and seasonal Irish cooking on Linen Quay in Galway. Lunch "
            "and dinner; groups of up to 8 can book with us by phone, bigger "
            "groups are booked by the team. Takeaway fish and chips Thursday "
            "to Sunday evenings."
        ),
        "opening_hours": (
            "Tue–Thu 12–3pm and 5–9.30pm, Fri–Sat 12–3pm and 5–10.30pm, "
            "Sun 12–8pm, closed Monday"
        ),
        "address": "Linen Quay, Galway",
        "website": "https://linen-quay.demo.lightmove.ai",
        "extra_info": (
            "Gluten-free and dairy-free options on every menu; tell us about "
            "allergies when you book. High chairs available. Dogs welcome on "
            "the terrace. Pay and display parking on the quay, free after "
            "6pm. Takeaway fish and chips Thu–Sun 5–9pm, collect at the side "
            "hatch. We don't give menu prices over the phone."
        ),
        "booking_questions": "party_size,allergies,occasion",
    },
    owner_name="Niamh Gallagher",
    staff_name="Ciarán Doyle",
    called_number="+353915550142",
    daily_calls=(1.3, 3.0, 3.2, 3.6, 4.6, 5.0, 3.8),
    hours=_hours(
        h9=0.5,
        h10=1.5,
        h11=3,
        h12=3.5,
        h13=2.5,
        h14=1.5,
        h15=1.5,
        h16=3,
        h17=4,
        h18=3.5,
        h19=2.5,
        h20=1.5,
        h21=0.8,
        h22=0.3,
    ),
    scenarios=[
        (30, _r_book),
        (8, _r_full),
        (6, _r_group),
        (9, _r_hours),
        (10, _r_question),
        (6, _r_takeaway),
        (7, _r_unanswered),
        (5, _r_change),
        (5, lambda c: _r_manager(c, True)),
        (3, lambda c: _r_manager(c, False)),
        (8, _silent),
    ],
    callers=_callers("linen-quay", ("85", "87", "86", "83", "89"), 70),
    closed_days=(0,),
    # Recent enough to be waiting on Home, and among the recorded calls.
    pinned={2: _r_polish},
)


# --- Halyard Telecom: a VoIP provider's support line, Dublin --------------------

TELECOM_NAME = "Halyard Telecom"
COMPANIES = [
    "Brady Accountants",
    "Westside Physio",
    "Corrigan Motors",
    "Hillview Vets",
    "Mullan Architects",
    "Kilbride Logistics",
    "Seaview Guesthouse",
    "Tobin Solicitors",
    "Rathmore Pharmacy",
    "Foley Engineering",
]


def _account(c: Ctx) -> str:
    return f"HT{c.rng.randint(10000, 99999)}"


def _account_words(account: str) -> str:
    return "H T " + " ".join(account[2:])


def _t_outage(c: Ctx, answered: bool | None) -> Plan:
    """A fault: put through to a technician (answered or not), or after
    hours a message for the on-call technician (``answered`` None)."""
    company = c.pick(COMPANIES)
    account = _account(c)
    problem, short = c.pick(
        [
            ("none of our phones are working since this morning", "All phones down"),
            ("we can make calls out but nothing is coming in", "No inbound calls"),
            (
                "the line keeps dropping calls after a minute or so",
                "Calls dropping after a minute",
            ),
            ("our desk phones all say no service", "Desk phones show no service"),
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi, this is {c.caller.name} from {company}, {problem}.")
    t.a("I'm sorry to hear that. Can I take your account number?")
    t.c(f"It's {_account_words(account)}.")
    if answered is None:
        t.a(
            "Thanks. I'll get this to the on-call technician straight away and they'll ring you back."
        )
        t.message()
        t.a("Can I have your name?")
        t.c(c.caller.name)
        t.a("And the best mobile to reach you on?")
        t.c(c.number_words())
        t.a(f"That's {c.number_words()}. Is that right?")
        t.c("Yes. Please hurry, we've customers trying to get through.")
        t.a(
            f"Understood. The technician has your account {_account_words(account)} and your number, and will call you shortly."
        )
        t.bye(f"Thanks for calling {TELECOM_NAME}.")
        return Plan(
            t.steps,
            CALLBACK,
            {
                "caller_name": c.caller.name,
                "callback_number": c.number_digits(),
                "call_reason": f"{short} at {company}, account {account}",
            },
            f"Reported a fault at {company} ({short.lower()}), account {account}. Wants the on-call technician to ring back.",
            "speak_to_someone",
        )
    t.a(
        "Thanks. I'll put you through to a technician now. One moment, I'm putting you through."
    )
    t.transfer(answered)
    if answered:
        return Plan(
            t.steps,
            TRANSFERRED,
            {
                "caller_name": c.caller.name,
                "call_reason": f"{short} at {company}, account {account}",
            },
            f"Reported a fault at {company}: {short.lower()}. Put through to a technician.",
            "speak_to_someone",
            status="transfer_call",
        )
    t.a(
        "I'm sorry, the technicians are all on calls right now. I'll take your details and the first one free will ring you."
    )
    t.message()
    t.a("What's your name?")
    t.c(c.caller.name)
    t.a("And your number?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. They'll call you as soon as they're free.")
    t.bye(f"Thanks for calling {TELECOM_NAME}.")
    return Plan(
        t.steps,
        TRANSFER_NOT_ANSWERED,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"{short} at {company}, account {account}",
        },
        f"Reported a fault at {company}: {short.lower()}. No technician picked up; left a number.",
        "speak_to_someone",
    )


def _t_billing(c: Ctx) -> Plan:
    question, answer, summary = c.pick(
        [
            (
                "When does the direct debit come out each month?",
                "Bills are issued on the first of the month and the direct debit is taken on the fifteenth.",
                "Asked when the direct debit is taken. Told the 15th; bills issue on the 1st.",
            ),
            (
                "Where can I see if there's an outage in my area?",
                "You can check live service status on the status page of our website. If your own lines are down, I can get a technician for you.",
                "Asked how to check for outages. Pointed to the status page.",
            ),
            (
                "How long does it take to port a number over to you?",
                "Porting takes five to ten working days once the porting form is signed.",
                "Asked how long porting takes. Told 5 to 10 working days after the form is signed.",
            ),
            (
                "What are your support hours?",
                "Support is open Monday to Friday eight till eight and Saturday nine till one. Outages are answered any time.",
                "Asked about support hours. Told the hours and that outages are answered 24/7.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(answer)
    t.c("Okay, that's great. Thanks.")
    t.bye(f"You're welcome. Thanks for calling {TELECOM_NAME}.")
    return Plan(t.steps, HANDLED, {"call_reason": question[:70]}, summary, "questions")


def _t_billing_message(c: Ctx) -> Plan:
    issue, short = c.pick(
        [
            ("I think we've been charged twice this month", "Charged twice this month"),
            (
                "our bill has gone up and nobody told us why",
                "Bill went up without notice",
            ),
            (
                "I need a copy of last month's invoice for the accountant",
                "Copy of last month's invoice",
            ),
        ]
    )
    company = c.pick(COMPANIES)
    t = Talk(c.greeting)
    t.c(f"Hi, I'm calling from {company}. {issue[0].upper() + issue[1:]}.")
    t.a(
        "I'll pass that to our accounts team so they can look at your account and call you back."
    )
    t.message()
    t.a("Can I take your name?")
    t.c(c.caller.name)
    t.a("And the best number for you?")
    t.c(c.number_words())
    t.a(
        f"That's {c.number_words()}. Accounts will be in touch, usually the same working day."
    )
    t.bye(f"Thanks for calling {TELECOM_NAME}.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Billing: {short.lower()} ({company})",
        },
        f"Billing query from {company}: {short.lower()}. Left a number for accounts.",
        "questions",
    )


def _t_porting(c: Ctx) -> Plan:
    company = c.pick(COMPANIES)
    t = Talk(c.greeting)
    t.c(
        f"Hi, we signed the form to move our numbers over to you two weeks ago and they still haven't moved. It's {company}."
    )
    t.a(
        "Sorry about the wait. Porting usually takes five to ten working days, so I'll get the porting team to check where it's at and call you."
    )
    t.message()
    t.a("What's your name?")
    t.c(c.caller.name)
    t.a("And a number to call you back on?")
    t.c(c.number_words())
    t.a(
        f"Thanks, {c.caller.first}. The porting team will ring you on {c.number_words()}."
    )
    t.bye(f"Thanks for calling {TELECOM_NAME}.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Number port overdue for {company}",
        },
        f"Chased a number port for {company} signed two weeks ago. Wants the porting team to call back.",
        "speak_to_someone",
    )


def _t_sales(c: Ctx) -> Plan:
    seats = c.pick([5, 8, 12, 20])
    t = Talk(c.greeting)
    t.c(
        f"Hello, we're opening a new office and we need a phone system for about {seats} people. Can someone give me a price?"
    )
    t.a(
        "I'd be glad to get our sales team to call you with a quote. Can I take a few details?"
    )
    t.message()
    t.a("What's your name?")
    t.c(c.caller.name)
    t.a("And your number?")
    t.c(c.number_words())
    t.a(
        f"That's {c.number_words()}. Sales will call you about a system for {seats} people."
    )
    t.bye(f"Thanks for calling {TELECOM_NAME}.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"New phone system for {seats} people, wants a quote",
        },
        f"Wants a quote for a phone system for {seats} people in a new office. Left a number for sales.",
        "speak_to_someone",
    )


def _t_unanswered(c: Ctx) -> Plan:
    question, short = c.pick(
        [
            (
                "Do you support Microsoft Teams Direct Routing?",
                "Do you support Teams Direct Routing?",
            ),
            ("Can you port a 1890 number?", "Can you port a 1890 number?"),
            (
                "Do your handsets work with a door entry system?",
                "Do the handsets work with door entry?",
            ),
            (
                "Is there a contract or is it month to month?",
                "Is it a contract or month to month?",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(
        "I'm sorry, I don't know that one. I can take your details and someone from the team will come back to you."
    )
    t.c("No, you're grand, I'll email instead. Thanks.")
    t.bye(f"No problem. Thanks for calling {TELECOM_NAME}.")
    return Plan(
        t.steps,
        UNANSWERED,
        {"call_reason": short},
        f"Asked: {short[0].lower() + short[1:]} Didn't get an answer.",
        "questions",
        unanswered=[short],
    )


def _t_accounts_transfer(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c(f"Hi, it's {c.caller.name}, could I speak to someone in accounts please?")
    t.a("Of course. One moment, I'm putting you through.")
    t.transfer(True)
    return Plan(
        t.steps,
        TRANSFERRED,
        {"caller_name": c.caller.name, "call_reason": "Wanted accounts"},
        "Asked for accounts. Put through to the team.",
        "speak_to_someone",
        status="transfer_call",
    )


TELECOM = Business(
    slug="halyard-telecom",
    name=TELECOM_NAME,
    kind="telecoms",
    template_name="VoIP phone receptionist",
    opening_hours=_week(
        *[(("08:00", "20:00"),)] * 5,
        (("09:00", "13:00"),),
        (),
        note="Outages answered 24/7.",
    ),
    facts={
        "business_name": TELECOM_NAME,
        "business_description": (
            "Business phone and broadband provider for Irish small and "
            "medium businesses: hosted VoIP phone systems, SIP trunks, number "
            "porting and business fibre. This is the customer support line."
        ),
        "opening_hours": (
            "Support Mon–Fri 8am–8pm and Sat 9am–1pm; outages answered 24/7"
        ),
        "address": "Unit 7, Halyard Business Park, Dublin 12",
        "website": "https://halyard-telecom.demo.lightmove.ai",
        "extra_info": (
            "Live service status is on the status page of our website. Bills "
            "issue on the 1st; direct debit is taken on the 15th. Porting a "
            "number takes 5–10 working days once the porting form is signed. "
            "For a fault, take the account number (it starts HT) and put the "
            "caller through to a technician. Sales and quotes: take a "
            "message for the sales team."
        ),
    },
    owner_name="Declan Brennan",
    staff_name="Aisling Moran",
    called_number="+35315550188",
    daily_calls=(4.6, 4.2, 4.0, 4.0, 3.6, 1.2, 0.6),
    hours=_hours(
        h0=0.2,
        h1=0.1,
        h6=0.2,
        h7=0.6,
        h8=2.5,
        h9=4.5,
        h10=4.5,
        h11=3.5,
        h12=2.5,
        h13=2.5,
        h14=3.5,
        h15=3.5,
        h16=3,
        h17=2,
        h18=1,
        h19=0.7,
        h20=0.4,
        h21=0.3,
        h22=0.2,
        h23=0.2,
    ),
    scenarios=[
        (17, lambda c: _t_outage(c, True)),
        (8, lambda c: _t_outage(c, False)),
        (7, lambda c: _t_outage(c, None)),
        (18, _t_billing),
        (10, _t_billing_message),
        (8, _t_porting),
        (8, _t_sales),
        (8, _t_unanswered),
        (6, _t_accounts_transfer),
        (8, _silent),
    ],
    callers=_callers("halyard-telecom", ("87", "86", "85", "83"), 70),
)


# --- Larchfield Dental: a family practice in Kilkenny ---------------------------

DENTAL_NAME = "Larchfield Dental"


def _d_book(c: Ctx) -> Plan:
    spoken, on, weekday = c.day(closed=(6,), soon=False)
    say, hhmm, written = c.pick(DAY_TIMES)
    kind = c.pick(
        ["a check-up", "a check-up", "a clean with the hygienist", "a filling"]
    )
    new = c.rng.random() < 0.3
    t = Talk(c.greeting)
    t.c(f"Hi, I'd like to make an appointment for {kind}, {spoken} if possible.")
    t.a("Of course. Are you a new or an existing patient?")
    t.c("I'm new, actually." if new else "Existing. I was in last year.")
    part = "morning" if hhmm < "12:00" else "afternoon"
    t.tool(
        CHECK_FN,
        {"relative_day": spoken.replace("on ", "").lower(), "part_of_day": part},
        {
            "slots": [{"id": _slot(on, hhmm), "say": f"{weekday} at {say}"}],
            "say": f"I have {weekday} at {say}.",
        },
    )
    t.a(f"I have {weekday} at {say}. Would that suit?")
    t.c("That's perfect.")
    t.a("Can I take your full name?")
    t.c(c.caller.name)
    t.a("And a mobile number?")
    t.c(c.number_words())
    t.a(
        f"So that's {kind} on {weekday} at {say}, for {c.caller.name}, {'a new' if new else 'an existing'} patient. Shall I book that?"
    )
    t.c("Yes please.")
    t.tool(
        BOOK_FN,
        {
            "slot_id": _slot(on, hhmm),
            "caller_name": c.caller.name,
            "caller_phone": c.number_digits(),
            "reason": kind.replace("a ", "", 1),
        },
        {
            "booked": True,
            "event_id": f"demo{c.rng.getrandbits(40):010x}",
            "say": f"That is booked in for {weekday} at {say}.",
            "starts_at": _slot(on, hhmm),
        },
    )
    if new:
        t.a(
            f"You're booked in for {weekday} at {say}. As a new patient, please arrive ten minutes early to fill in a form."
        )
    else:
        t.a(f"You're booked in for {weekday} at {say}.")
    t.c("Lovely, thanks.")
    t.bye(f"Thank you for calling {DENTAL_NAME}. Goodbye.")
    return Plan(
        t.steps,
        BOOKING_MADE,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": kind[2:].capitalize() if kind.startswith("a ") else kind,
            "booking_outcome": "booked",
            "booking_date": on,
            "booking_time": hhmm,
            "appointment_type": kind.replace("a ", "", 1),
            "patient_status": "new" if new else "existing",
        },
        f"Booked {kind} {spoken} at {written} for {'a new' if new else 'an existing'} patient.",
        "appointments",
    )


def _d_full(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c("Hi, have you anything on Saturday morning for a check-up?")
    t.tool(
        CHECK_FN,
        {"relative_day": "saturday", "part_of_day": "morning"},
        {
            "slots": [],
            "say": "Saturday morning is fully booked. The next free times are Thursday at half five or Friday at nine.",
        },
    )
    t.a(
        "I'm sorry, Saturday morning is fully booked. The next free times are Thursday at half five or Friday at nine."
    )
    t.c("Ah, I work weekdays. I'll leave it for now and ring again.")
    t.bye(f"No problem at all. Thanks for calling {DENTAL_NAME}.")
    return Plan(
        t.steps,
        TIME_WAS_FULL,
        {
            "call_reason": "Wanted a Saturday morning check-up",
            "appointment_type": "check-up",
        },
        "Wanted a check-up on Saturday morning, which was full. Couldn't do Thursday 5:30 pm or Friday 9:00 am.",
        "appointments",
        time_was_full=True,
    )


def _d_pain(c: Ctx, answered: bool | None) -> Plan:
    problem, short = c.pick(
        [
            (
                "I've a really bad toothache since last night",
                "Bad toothache since last night",
            ),
            ("I broke a tooth eating and it's sharp", "Broken tooth"),
            ("my crown came off this morning", "Crown came off"),
            (
                "my son knocked his front tooth playing hurling",
                "Child knocked a front tooth",
            ),
        ]
    )
    t = Talk(c.greeting)
    intro = "Hi" if answered is None else f"Hi, it's {c.caller.name}"
    t.c(f"{intro}, {problem}. Can someone see me today?")
    t.a(
        "I'm sorry to hear that. If the pain is severe or there's swelling in your face, please go to A and E. We keep emergency slots every morning."
    )
    if answered is None:
        t.a("I'll ask reception to call you about an emergency slot.")
        t.message()
        t.a("Can I take your name?")
        t.c(c.caller.name)
        t.a("And the best number?")
        t.c(c.number_words())
        t.a(f"That's {c.number_words()}. Reception will ring you first thing.")
        t.bye(f"Thank you for calling {DENTAL_NAME}. Take care.")
        return Plan(
            t.steps,
            CALLBACK,
            {
                "caller_name": c.caller.name,
                "callback_number": c.number_digits(),
                "call_reason": f"{short}, wants an emergency slot",
                "appointment_type": "emergency",
            },
            f"{short}; asked to be seen today. Left a number for reception to offer an emergency slot.",
            "urgent",
        )
    t.a("Let me put you through to reception. One moment, I'm putting you through.")
    t.transfer(answered)
    if answered:
        return Plan(
            t.steps,
            TRANSFERRED,
            {
                "caller_name": c.caller.name,
                "call_reason": f"{short}, wants to be seen today",
                "appointment_type": "emergency",
            },
            f"{short}; wanted to be seen today. Put through to reception.",
            "urgent",
            status="transfer_call",
        )
    t.a(
        "I'm sorry, reception can't pick up just now. I'll take your details so they ring you back."
    )
    t.message()
    t.a("Your name, please?")
    t.c(c.caller.name)
    t.a("And your number?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. Reception will call you as soon as they're free.")
    t.bye(f"Thank you for calling {DENTAL_NAME}.")
    return Plan(
        t.steps,
        TRANSFER_NOT_ANSWERED,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"{short}, wants to be seen today",
            "appointment_type": "emergency",
        },
        f"{short}; wanted to be seen today. Reception didn't pick up; left a number.",
        "urgent",
    )


def _d_portuguese(c: Ctx) -> Plan:
    """A caller who speaks Portuguese, offered staff or a call back in one
    Portuguese line; the number is taken in English."""
    name = "Rafael Costa"
    t = Talk(c.greeting)
    t.c("Bom dia, preciso marcar uma limpeza dos dentes, por favor.")
    t.a(
        "Desculpe, só posso ajudar em inglês. Posso transferir para um "
        "funcionário, ou anotar o seu número para alguém ligar de volta."
    )
    t.c("Ah, OK. Call back, please.")
    t.message()
    t.a("Of course. Can I take your name?")
    t.c(name)
    t.a("And the best number for you?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. Reception will call you back.")
    t.bye(f"Thank you for calling {DENTAL_NAME}.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": name,
            "callback_number": c.number_digits(),
            "call_reason": "Wants to book a cleaning (spoke Portuguese)",
            "appointment_type": "cleaning",
        },
        "Asked in Portuguese to book a cleaning. Was offered a call back and "
        "left a number.",
        "appointments",
        caller_language="pt",
        caller_voice="pt-BR-Chirp3-HD-Puck",
    )


def _d_emergency(c: Ctx) -> Plan:
    """An emergency: the agent sends the caller to 112/999 at once and ends
    the call, without triage or a message (the template's emergency rule)."""
    t = Talk(c.greeting)
    t.c(
        "Hi, my face has swollen up really badly since this morning and I'm "
        "finding it hard to swallow and breathe."
    )
    t.a(
        "Please hang up now and dial 112 or 999. The emergency services can "
        "help you straight away."
    )
    t.c("OK. OK, thanks.")
    t.bye("Take care.")
    return Plan(
        t.steps,
        HANDLED,
        {"call_reason": "Facial swelling, trouble swallowing and breathing"},
        "Described facial swelling and trouble breathing. Was told to hang up "
        "and dial 112 or 999.",
        "urgent",
        emergency=True,
    )


def _d_question(c: Ctx) -> Plan:
    question, answer, summary = c.pick(
        [
            (
                "How much is a check-up?",
                "A check-up and clean is ninety-five euro. If you have PRSI, the dental benefit covers a free exam once a year.",
                "Asked the price of a check-up. Told €95, and about the PRSI free exam.",
            ),
            (
                "Are you open on Saturdays?",
                "Yes, we're open Saturday from nine until one.",
                "Asked about Saturday hours. Told 9:00 am to 1:00 pm.",
            ),
            (
                "Is there parking at the practice?",
                "There's free parking behind the practice.",
                "Asked about parking. Told free parking behind the practice.",
            ),
            (
                "Do you do braces?",
                "We don't do orthodontics here, but we refer patients to a specialist.",
                "Asked about braces. Told the practice refers to a specialist.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(answer)
    t.c("Okay, thanks very much.")
    t.bye(f"You're welcome. Thank you for calling {DENTAL_NAME}.")
    return Plan(t.steps, HANDLED, {"call_reason": question[:60]}, summary, "questions")


def _d_new_family(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c(
        "Hi, we've just moved to Kilkenny and I'd like to register the whole family, two adults and two children."
    )
    t.a(
        "You're very welcome. I'll take your details and reception will call to set up the appointments."
    )
    t.message()
    t.a("Can I have your name?")
    t.c(c.caller.name)
    t.a("And the best number?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. Reception will be in touch.")
    t.bye(f"Thank you for calling {DENTAL_NAME}.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": "Register a family of four as new patients",
            "patient_status": "new",
        },
        "New to the area; wants to register a family of four. Left a number for reception.",
        "appointments",
    )


def _d_change(c: Ctx) -> Plan:
    spoken, on, _ = c.day(closed=(6,), soon=False)
    t = Talk(c.greeting)
    t.c(f"Hi, I need to cancel my appointment {spoken}, something's come up at work.")
    t.a(
        "No problem. I'll pass it to reception so they can cancel it and offer you a new time."
    )
    t.message()
    t.a("Your full name, please?")
    t.c(c.caller.name)
    t.a("And your number?")
    t.c(c.number_words())
    t.a("Thanks. Reception will call you to rebook.")
    t.bye(f"Thank you for calling {DENTAL_NAME}.")
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Cancel appointment {spoken.replace('on ', '')} and rebook",
            "booking_outcome": "requested",
            "booking_date": on,
            "patient_status": "existing",
        },
        f"Asked to cancel an appointment {spoken} and rebook. Waiting for reception.",
        "changes",
    )


def _d_unanswered(c: Ctx) -> Plan:
    question, short = c.pick(
        [
            ("Do you take VHI dental cover?", "Do you take VHI dental cover?"),
            (
                "Is the practice wheelchair accessible?",
                "Is the practice wheelchair accessible?",
            ),
            (
                "Do you do teeth whitening, and how much is it?",
                "How much is teeth whitening?",
            ),
            (
                "Can I pay in instalments for an implant?",
                "Can implants be paid in instalments?",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(
        "I'm sorry, I don't have that information. I can take your number and reception will get back to you."
    )
    t.c("It's okay, I'll call back during the week.")
    t.bye(f"No problem. Thank you for calling {DENTAL_NAME}.")
    return Plan(
        t.steps,
        UNANSWERED,
        {"call_reason": short},
        f"Asked: {short[0].lower() + short[1:]} Didn't get an answer.",
        "questions",
        unanswered=[short],
    )


DENTAL = Business(
    slug="larchfield-dental",
    name=DENTAL_NAME,
    kind="dental",
    template_name="Clinic receptionist",
    opening_hours=_week(
        *[(("08:30", "18:00"),)] * 4,
        (("08:30", "16:00"),),
        (("09:00", "13:00"),),
        (),
    ),
    facts={
        "business_name": DENTAL_NAME,
        "business_description": (
            "Family dental practice in Kilkenny city. Check-ups, hygiene, "
            "fillings, crowns, whitening and emergency appointments. New "
            "patients welcome; PRSI and medical card patients seen."
        ),
        "opening_hours": "Mon–Thu 8.30am–6pm, Fri 8.30am–4pm, Sat 9am–1pm, closed Sunday",
        "address": "14 Larchfield Road, Kilkenny",
        "website": "https://larchfield-dental.demo.lightmove.ai",
        "extra_info": (
            "New patients please arrive 10 minutes early. A check-up and "
            "clean is €95; PRSI dental benefit covers a free exam once a "
            "year. Emergency slots are held every morning from 8.30. Free "
            "parking behind the practice. We don't do orthodontics; we "
            "refer to a specialist."
        ),
        "booking_questions": "purpose,patient_status",
    },
    owner_name="Orla Keane",
    staff_name="Sinéad Fitzgerald",
    called_number="+353565550123",
    daily_calls=(4.4, 3.3, 3.0, 3.0, 2.6, 1.4, 0.2),
    hours=_hours(
        h7=0.3,
        h8=3.5,
        h9=4,
        h10=3,
        h11=2.5,
        h12=2,
        h13=2.5,
        h14=2.2,
        h15=2,
        h16=1.6,
        h17=1,
        h18=0.4,
        h19=0.3,
        h20=0.2,
        h21=0.1,
    ),
    scenarios=[
        (26, _d_book),
        (7, _d_full),
        (8, lambda c: _d_pain(c, None)),
        (5, lambda c: _d_pain(c, True)),
        (3, lambda c: _d_pain(c, False)),
        (13, _d_question),
        (6, _d_new_family),
        (7, _d_change),
        (6, _d_unanswered),
        (8, _silent),
    ],
    callers=_callers("larchfield-dental", ("87", "86", "85", "89"), 60),
    pinned={3: _d_portuguese, 11: _d_emergency},
    closed_days=(6,),
)


# --- Tidewell Plumbing & Heating: a trades business in Cork ---------------------

TRADES_NAME = "Tidewell Plumbing & Heating"
PLACES = [
    "Douglas",
    "Ballincollig",
    "Blackrock",
    "Carrigaline",
    "Bishopstown",
    "Glanmire",
    "Midleton",
    "Mahon",
    "Togher",
    "Passage West",
]


def _job(
    c: Ctx,
    *,
    problem: str,
    short: str,
    urgency: str,
    reason: str,
    answered: bool | None = None,
) -> Plan:
    """A job taken down for a call back, or (``answered`` set) an emergency
    put through to the engineer on call."""
    place = c.pick(PLACES)
    house = c.rng.randint(2, 48)
    road = c.pick(
        [
            "Maple Grove",
            "Church Road",
            "Riverside Park",
            "Oakfield Drive",
            "The Paddocks",
        ]
    )
    address = f"{house} {road}, {place}"
    t = Talk(c.greeting)
    t.c(problem if answered is None else f"{problem} It's {c.caller.name}.")
    if answered is not None:
        t.a("That sounds urgent. Is there any smell of gas or any danger?")
        t.c("No gas, just water everywhere.")
        t.a(
            "Okay. Turn off the water at the stopcock if you can. I'll put you through to the engineer on call. One moment, I'm putting you through."
        )
        t.transfer(answered)
        if answered:
            return Plan(
                t.steps,
                TRANSFERRED,
                {
                    "caller_name": c.caller.name,
                    "call_reason": short,
                    "urgency": urgency,
                },
                f"{short}. Put through to the engineer on call.",
                reason,
                status="transfer_call",
            )
        t.a(
            "I'm sorry, the engineer can't pick up right now, they may be on a job. I'll take the details so they ring you straight back."
        )
    else:
        t.a(
            "I can take the details and get someone to ring you back. What's the address?"
        )
        t.c(f"{house} {road}, in {place}.")
    t.message()
    t.a("And your name?")
    t.c(c.caller.name)
    t.a("What's the best number to reach you?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. Is that right?")
    t.c("That's right.")
    if answered is not None:
        t.a("What's the address?")
        t.c(f"{house} {road}, {place}.")
    when = (
        "as soon as possible"
        if urgency == "emergency"
        else "today"
        if urgency == "this week"
        else "in the next day or two"
    )
    t.a(
        f"Thanks, {c.caller.first}. Someone from {TRADES_NAME} will call you back {when}."
    )
    t.bye("Thanks for calling. Bye now.")
    return Plan(
        t.steps,
        TRANSFER_NOT_ANSWERED if answered is False else CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": short,
            "job_address": address,
            "urgency": urgency,
        },
        (
            f"{short} in {place}. The engineer on call didn't pick up; left a number."
            if answered is False
            else f"{short} in {place}. Left a number for a call back."
        ),
        reason,
    )


def _p_burst(c: Ctx, answered: bool) -> Plan:
    problem, short = c.pick(
        [
            (
                "Hi, a pipe has burst under the kitchen sink and it's pouring out.",
                "Burst pipe under the kitchen sink",
            ),
            (
                "There's water coming through the ceiling from the bathroom upstairs.",
                "Water leaking through the ceiling",
            ),
            (
                "The hot water cylinder is leaking all over the hot press.",
                "Hot water cylinder leaking",
            ),
        ]
    )
    return _job(
        c,
        problem=problem,
        short=short,
        urgency="emergency",
        reason="urgent",
        answered=answered,
    )


def _p_no_heat(c: Ctx) -> Plan:
    problem, short = c.pick(
        [
            (
                "Hi, the boiler's stopped and we've no heat or hot water.",
                "Boiler stopped, no heat or hot water",
            ),
            (
                "Our boiler keeps losing pressure and cutting out.",
                "Boiler losing pressure",
            ),
            (
                "The radiators upstairs aren't heating at all.",
                "Upstairs radiators not heating",
            ),
        ]
    )
    return _job(c, problem=problem, short=short, urgency="this week", reason="urgent")


def _p_service(c: Ctx) -> Plan:
    return _job(
        c,
        problem="Hi, I'd like to get the gas boiler serviced before the winter.",
        short="Gas boiler service",
        urgency="no rush",
        reason="new_job",
    )


def _p_quote(c: Ctx) -> Plan:
    problem, short = c.pick(
        [
            (
                "Hello, we're looking for a quote to redo our bathroom.",
                "Quote for a new bathroom",
            ),
            (
                "Hi, we're thinking about a heat pump and would like a quote.",
                "Quote for a heat pump",
            ),
            (
                "Hi, could I get a price to move a radiator and add another one?",
                "Quote to move and add a radiator",
            ),
        ]
    )
    return _job(c, problem=problem, short=short, urgency="no rush", reason="new_job")


def _p_existing(c: Ctx) -> Plan:
    problem, short = c.pick(
        [
            (
                "Hi, one of your lads fixed our radiator on Tuesday but it's dripping again.",
                "Radiator fixed Tuesday is dripping again",
            ),
            (
                "I'm ringing about the invoice for last week's job, I think it's wrong.",
                "Query about last week's invoice",
            ),
            (
                "Hi, when is the engineer coming to finish the shower?",
                "When will the shower job be finished?",
            ),
        ]
    )
    return _job(
        c, problem=problem, short=short, urgency="this week", reason="existing_job"
    )


def _p_question(c: Ctx) -> Plan:
    question, answer, summary = c.pick(
        [
            (
                "How much is a call-out?",
                "A standard call-out is ninety euro, which includes the first half hour. Evenings and weekends are a hundred and fifty.",
                "Asked the call-out fee. Told €90 weekdays, €150 evenings and weekends.",
            ),
            (
                "Do you cover Kinsale?",
                "Yes, we cover Cork city and county, out as far as Mallow, Midleton and Kinsale.",
                "Asked if Kinsale is covered. Told yes.",
            ),
            (
                "How much is a boiler service?",
                "A boiler service is a hundred and twenty euro, done by an RGII-registered engineer for gas.",
                "Asked the price of a boiler service. Told €120.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(answer)
    t.c("Grand, thanks. I'll ring back to book.")
    t.bye(f"No bother. Thanks for calling {TRADES_NAME}.")
    return Plan(t.steps, HANDLED, {"call_reason": question[:60]}, summary, "questions")


def _p_unanswered(c: Ctx) -> Plan:
    question, short = c.pick(
        [
            ("Do you cover Youghal?", "Do you cover Youghal?"),
            ("Do you install electric showers?", "Do you install electric showers?"),
            ("Do you service oil boilers as well?", "Do you service oil boilers?"),
            (
                "Can you do a SEAI grant job for a heat pump?",
                "Do you do SEAI grant heat pump jobs?",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(question)
    t.a(
        "I'm not sure about that, sorry. I can take your number and someone will ring you back."
    )
    t.c("No, it's okay, I'll try again tomorrow.")
    t.bye(f"No problem. Thanks for calling {TRADES_NAME}.")
    return Plan(
        t.steps,
        UNANSWERED,
        {"call_reason": short},
        f"Asked: {short[0].lower() + short[1:]} Didn't get an answer.",
        "questions",
        unanswered=[short],
    )


TRADES = Business(
    slug="tidewell-plumbing",
    name=TRADES_NAME,
    kind="trades",
    template_name="Trades after-hours",
    # Emergencies are put through to the on-call plumber at any hour.
    opening_hours=_week(
        *[(("08:00", "18:00"),)] * 5,
        (("09:00", "13:00"),),
        (),
        note="Emergency call-outs evenings and weekends.",
        transfer_only_when_open=False,
    ),
    facts={
        "business_name": TRADES_NAME,
        "business_description": (
            "Plumbing and heating across Cork city and county: boiler "
            "servicing and repairs, burst pipes and leaks, heat pumps and "
            "bathroom installs. Emergency call-outs 7 days."
        ),
        "opening_hours": (
            "Mon–Fri 8am–6pm, Sat 9am–1pm; emergency call-outs evenings and weekends"
        ),
        "address": "Unit 3, Riverbank Enterprise Centre, Cork",
        "website": "https://tidewell-plumbing.demo.lightmove.ai",
        "extra_info": (
            "We cover Cork city and county out to Mallow, Midleton and "
            "Kinsale. Standard call-out €90 including the first half hour; "
            "evenings and weekends €150. Boiler service €120; gas work by "
            "RGII-registered engineers. Free quotes for bathrooms and heat "
            "pumps after a site visit."
        ),
    },
    owner_name="Pádraig Kinsella",
    staff_name="Emma Whelan",
    called_number="+353215550167",
    daily_calls=(3.6, 3.0, 2.8, 2.8, 2.8, 2.0, 1.5),
    hours=_hours(
        h0=0.2,
        h6=0.3,
        h7=1.5,
        h8=3,
        h9=3,
        h10=2.5,
        h11=2,
        h12=1.6,
        h13=1.8,
        h14=1.8,
        h15=1.8,
        h16=2,
        h17=2.5,
        h18=2.5,
        h19=2,
        h20=1.4,
        h21=1,
        h22=0.6,
        h23=0.3,
    ),
    scenarios=[
        (7, lambda c: _p_burst(c, True)),
        (5, lambda c: _p_burst(c, False)),
        (17, _p_no_heat),
        (12, _p_service),
        (14, _p_quote),
        (9, _p_existing),
        (13, _p_question),
        (8, _p_unanswered),
        (10, _silent),
    ],
    callers=_callers("tidewell-plumbing", ("87", "86", "85", "83"), 60),
)


BUSINESSES: list[Business] = [RESTAURANT, TELECOM, DENTAL, TRADES]


def fit_to_opening_hours(plan: Plan, c: Ctx) -> Plan:
    """The call as it goes with the live transfer gate: when the business
    passes calls only during opening hours and the call came in while it was
    closed, a call that would have put the caller through (answered or not)
    rings nobody instead. The transfer tool returns its ``closed`` result, the
    agent says the team isn't available and offers to take a message: most
    callers leave one (a callback), the rest say they'll ring back (handled).
    Any other call is returned as it is."""
    from api.services.workflow.opening_hours import is_open

    hours = c.business.opening_hours
    at = next((i for i, s in enumerate(plan.steps) if s.kind == "transfer"), None)
    if (
        at is None
        or hours is None
        or not hours.transfer_only_when_open
        or is_open(hours, c.started)
    ):
        return plan
    t = Talk("")
    t.steps = [*plan.steps[:at], Step("transfer", answered=False, closed=True)]
    if any(s.kind == "move" and s.target == "stage_1" for s in t.steps):
        t.node = "stage_1"
    reason = plan.captured.get("call_reason") or "Asked for a person"
    name = c.business.name
    t.a(
        "I'm sorry, the team isn't available right now, we're closed at the "
        "moment. Can I take a message so someone calls you back?"
    )
    if c.rng.random() < 0.75:
        t.c("Yes, please.")
        if t.node != "stage_1":
            t.message()
        t.a("What's your name?")
        t.c(c.caller.name)
        t.a("And the best number for you?")
        t.c(c.number_words())
        t.a(f"That's {c.number_words()}. The team will call you back when we open.")
        t.bye(f"Thanks for calling {name}.")
        return Plan(
            t.steps,
            CALLBACK,
            {
                "caller_name": c.caller.name,
                "callback_number": c.number_digits(),
                "call_reason": reason,
            },
            f"Asked for a person while {name} was closed: "
            f"{reason[:1].lower()}{reason[1:]}. Left a number for a call back.",
            plan.reason,
        )
    t.c("No, it's fine, I'll ring back when you're open.")
    t.a("No problem at all.")
    t.bye(f"Thanks for calling {name}.")
    return Plan(
        t.steps,
        HANDLED,
        {"caller_name": c.caller.name, "call_reason": reason},
        f"Asked for a person while {name} was closed; will ring back during "
        "opening hours.",
        plan.reason,
    )


def call_dates(
    business: Business, now_local: datetime, days: int = 30
) -> list[datetime]:
    """When the calls came in, newest first: each past day's count from the
    weekday's average, at the business's busy hours; today only up to now,
    with at least a handful of calls."""
    times: list[datetime] = []
    today: date = now_local.date()
    for back in range(days):
        day = today - timedelta(days=back)
        rng = random.Random(f"{business.slug}:{day.isoformat()}")
        mean = business.daily_calls[day.weekday()]
        count = max(0, round(rng.gauss(mean, mean * 0.3)))
        hours = list(range(24))
        weights = list(business.hours)
        if back == 0:
            # Today: a busier day so far, so the dashboard has a story.
            count = max(count + 2, 5)
        for _ in range(count):
            hour = rng.choices(hours, weights)[0]
            moment = datetime.combine(
                day, datetime.min.time(), now_local.tzinfo
            ) + timedelta(
                hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
            )
            times.append(moment)
    # Nothing in the last few minutes or the future.
    latest = now_local - timedelta(minutes=4)
    past = [t for t in times if t <= latest]
    start = datetime.combine(today, datetime.min.time(), now_local.tzinfo)
    so_far = [t for t in past if t >= start]
    # Once the morning is under way, today shows a handful of calls at the
    # hours already gone (refresh on the day of a demo; just after
    # midnight today is honestly quiet).
    gone = [h for h in range(now_local.hour) if business.hours[h] > 0]
    if now_local.hour >= 10 and len(so_far) < 5 and gone:
        rng = random.Random(f"{business.slug}:today:{today.isoformat()}")
        for _ in range(5 - len(so_far)):
            hour = rng.choices(gone, [business.hours[h] for h in gone])[0]
            past.append(
                start
                + timedelta(
                    hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
                )
            )
    return sorted(past, reverse=True)
