"""CH Marine: a demo account for a real prospective partner, built on facts
from their own website.

Used by ``api.scripts.seed_demo_accounts`` (``--only chmarine``). Unlike the
four invented businesses in ``demo_businesses.py``, CH Marine is a real Irish
chandlery (https://www.chmarine.com). Everything the agent says about the
business comes from their site as read on 8 November 2026: the stores and
their hours, delivery and returns, lifejacket servicing, and a sample of
product prices. The prices are dated in the price list and the agent says
they can change. What is made up, and marked as such: the callers, their
calls, and the 20 sample orders the order lookup reads.

Beyond the shared seed (workspace, logins, agent from the AI Receptionist
starter, a month of calls) this business adds, all owned by the demo
workspace and removed with it:

* the "retail" call-review reasons and report pack (``template_category``);
* a price-list document in the knowledge base, searched by the agent;
* the closing offer to connect the caller with the team, as a business fact
  the owner can edit, and the line's own rules in the agent's instructions;
* 20 sample orders (``DEMO_SAMPLE_ORDERS``) and a "Look up an order" HTTP
  tool calling ``/api/v1/demo/sample-orders/lookup`` with a bearer key
  (``api/services/demo_orders.py`` enforces the verification).
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from api.scripts.demo_businesses import (
    CALLBACK,
    HANDLED,
    TRANSFER_NOT_ANSWERED,
    TRANSFERRED,
    UNANSWERED,
    Business,
    Ctx,
    Plan,
    Talk,
    _callers,
    _hours,
    _silent,
    _week,
)
from api.services import demo_orders

NAME = "CH Marine"
SLUG = "chmarine"
FETCHED = "8 November 2026"
FETCHED_SHORT = "8 Nov 2026"
SITE = "https://www.chmarine.com"
PRICE_LIST_FILE = "CH Marine price list - chmarine.com 8 Nov 2026.md"
KB_FUNCTION = "retrieve_from_knowledge_base"
ORDER_TOOL_NAME = "Look up an order"
ORDER_FUNCTION = "look_up_an_order"
CREDENTIAL_NAME = "CH Marine order lookup (demo sample orders)"
RULES_MARKER = "## Rules for the CH Marine line"
CLOSING_OFFER_KEY = "closing_offer"
# Where the API reaches its own sample-order lookup (inside its container).
LOOKUP_URL = "http://localhost:8000/api/v1/demo/sample-orders/lookup"


# --- products, as listed on chmarine.com on 8 November 2026 ----------------


@dataclass(frozen=True)
class Product:
    section: str
    name: str
    price: str  # as listed, e.g. "€349.95" or "€1.60 to €8.45 per metre"
    url: str
    # What the product page said about availability that day, if it said.
    availability: str | None = None
    note: str | None = None


PRODUCTS: tuple[Product, ...] = (
    Product(
        "Safety: personal locator beacons",
        "Ocean Signal RescueME PLB1 Personal Locator Beacon, for Ireland registration",
        "€349.95",
        f"{SITE}/ocean-signal-rescueme-plb1-plb/",
        "in stock",
        "A flotation pouch can be added when ordering.",
    ),
    Product(
        "Safety: personal locator beacons",
        "Ocean Signal Flotation Pouch for RescueME PLB1",
        "€26.95",
        f"{SITE}/ocean-signal-flotation-pouch-for-rescueme-plb1/",
    ),
    Product(
        "Safety: personal locator beacons",
        "Ocean Signal LB7P PLB1 Replacement Battery Kit",
        "€78.95",
        f"{SITE}/ocean-signal-lb7p-plb1-replacement-battery-kit/",
    ),
    Product(
        "Safety: lifejackets (adult)",
        "Crewsaver Crewfit 150N ISO Automatic Lifejacket",
        "€138.95",
        f"{SITE}/crewsaver-crewfit-150n-iso-automatic-lifejacket/",
        "out of stock",
    ),
    Product(
        "Safety: lifejackets (adult)",
        "Plastimo Seapack Inflatable Lifejacket 150N",
        "€73.95",
        f"{SITE}/plastimo-seapack-inflatable-lifejacket-150n/",
        "in stock",
    ),
    Product(
        "Safety: lifejackets (adult)",
        "Spinlock Elite Lifejacket Re-arming Kit (33g cylinder)",
        "€36.95",
        f"{SITE}/spinlock-elite-lifejacket-re-arming-kit-33g-cylinder/",
    ),
    Product(
        "Safety: lifejackets for babies and children",
        "Crewsaver Supersafe Child's Lifejacket with Harness",
        "€89.95 to €103.95 depending on size",
        f"{SITE}/crewsaver-supersafe-childs-lifejacket/",
        "out of stock",
        "Price depends on the size chosen; the size guide is on the product page.",
    ),
    Product(
        "Safety: lifejackets for babies and children",
        "Baltic Skipper 1280 Lifejacket, baby and junior sizes",
        "€39.95 to €47.95 depending on size",
        f"{SITE}/baltic-skipper-lifejacket-1280-baby-junior-sizes/",
    ),
    Product(
        "Anodes",
        "MGDuff Cut Down Skeg MYA1 Anode CM6644537101M, Yamaha and Honda outboards, magnesium",
        "€13.95",
        f"{SITE}/mgduff-cut-down-skeg-mya1-anode-cm6644537101m-yamaha-honda-magnesium/",
        "in stock",
        "Which anode fits depends on the exact engine model: the team checks.",
    ),
    Product(
        "Anodes",
        "MGDuff Button Anode ZD56, zinc, 100mm",
        "€16.95",
        f"{SITE}/mgduff-button-anode/",
    ),
    Product(
        "Anodes",
        "MGDuff Volvo Penta 290 Drive Anode Kit CMV290KIT, zinc",
        "€89.95",
        f"{SITE}/mg-duff-volvo-penta-290-drive-anode-kit-cmv290kit-zinc/",
    ),
    Product(
        "Pumps",
        "Jabsco Amazon Universal manual bilge pump, 38mm",
        "€141.95",
        f"{SITE}/amazon-universal-manual-pump-29270-0000/",
        "in stock",
    ),
    Product(
        "Pumps",
        "Rule 1100 Bilge Pump, 12 volt",
        "€77.95",
        f"{SITE}/rule-1100-bilge-pump/",
        "in stock",
    ),
    Product(
        "Antifouling",
        "International Micron 350 Antifoul, 2.5 litre",
        "€164.95",
        f"{SITE}/international-micron-350-antifoul-2-5l/",
        "in stock",
        "How much a hull needs depends on the boat: the team advises.",
    ),
    Product(
        "Antifouling",
        "International Cruiser 250 Antifoul, 750ml",
        "€49.95",
        f"{SITE}/international-cruiser-250-750ml-antifoul/",
    ),
    Product(
        "Antifouling",
        "International Cruiser 250 Antifoul, 3 litre",
        "€132.95",
        f"{SITE}/international-cruiser-250-antifoul-3L/",
    ),
    Product(
        "Rope",
        "Marlow Marlowbraid rope, sold by the metre",
        "€1.60 to €8.45 per metre depending on the diameter",
        f"{SITE}/marlow-braid-rope/",
        "in stock",
        "Ordering a quantity of 1 is one metre. The price for a given "
        "diameter is shown on the product page.",
    ),
    Product(
        "Electrical",
        "Victron Blue Smart IP67 Battery Charger, 12V 17A / 24V 8A, Bluetooth",
        "€180.95",
        f"{SITE}/victron-blue-smart-ip67-battery-charger-12v-17a-24v-8a-bluetooth-cee-plug/",
        "in stock",
    ),
    Product(
        "Navigation: compasses",
        "Plastimo Iris 50 hand bearing compass with night illumination, blue",
        "€89.95",
        f"{SITE}/plastimo-iris-50-hand-bearing-compass-with-night-illumination-blue/",
        "in stock",
    ),
    Product(
        "Navigation: compasses",
        "Plastimo Iris 100 Compass, blue trim",
        "€99.95 (was €122.95)",
        f"{SITE}/plastimo-iris-100-compass-blue/",
    ),
    Product(
        "Clothing: Musto",
        "Musto Sardinia BR1 Women's Jacket 2.0, navy (Cork Week 2026 range)",
        "€99.95 (was €169.00)",
        f"{SITE}/cork-week-2026-musto-sardinia-br1-jacket-2-0-women-navy/",
        "in stock",
        "Sizes are chosen on the product page; stock by size isn't in this list.",
    ),
    Product(
        "Clothing: Musto",
        "Musto Essential Softshell Men's Jacket, navy (Cork Week 2026 range)",
        "€90.95 (was €129.95)",
        f"{SITE}/cork-week-2026-musto-essential-softshell-jacket-navy-men/",
    ),
    Product(
        "Clothing: Musto",
        "Musto Women's Fenland Jacket, navy",
        "€290.00",
        f"{SITE}/musto-women-s-fenland-jacket-navy/",
    ),
)


def price_list_markdown() -> str:
    """The knowledge-base document the agent searches."""
    lines = [
        "# CH Marine price list (sample)",
        "",
        f"Prices as listed on chmarine.com on {FETCHED}, including VAT. Prices "
        "can change: the website or a member of the team confirms the final "
        "price. This is a sample of about twenty products, not the full "
        "catalogue. Stock levels are not included: where a product page "
        f"showed 'in stock' or 'out of stock' on {FETCHED}, that is noted, "
        "and it may have changed since.",
        "",
    ]
    section = None
    for product in PRODUCTS:
        if product.section != section:
            section = product.section
            lines += [f"## {section}", ""]
        line = f"- {product.name}: {product.price}."
        if product.availability:
            line += f" Showed as {product.availability} on {FETCHED_SHORT}."
        if product.note:
            line += f" {product.note}"
        line += f" Product page: {product.url}"
        lines.append(line)
        if (
            product is PRODUCTS[-1]
            or PRODUCTS[PRODUCTS.index(product) + 1].section != section
        ):
            lines.append("")
    lines += [
        "## Not in this list",
        "",
        "Any product, size or colour not listed above: there is no price for "
        "it here. Don't guess one: point the caller to chmarine.com or offer "
        "a member of the team.",
        "",
        "## Stores",
        "",
        "- Cork (Frankfield): Frankfield Industrial Estate, Frankfield Road, "
        "Cork T12 KA99. Phone +353 21 431 5700. Monday to Friday 9am to "
        "5.30pm, Saturday 9am to 5pm.",
        "- Skibbereen: Nautic House, Marsh Rd, Skibbereen, Co. Cork P81 R230. "
        "Phone +353 28 23190. Monday to Friday 9am to 5.30pm, Saturday 9am to 5pm.",
        "- Newtownards: Scrabo Business Park, Jubilee Rd, Newtownards, Co. "
        "Down BT23 4YH. Phone +44 28 9182 8405. Monday to Friday 9am to 4.30pm.",
        "- Kilkeel (KTS Sea Safety): The Harbour, Kilkeel, Co. Down BT34 4AX. "
        "Phone +44 28 4176 2655. Monday to Friday 8.30am to 5pm, Saturday 9am to 12pm.",
        "- No Sunday or bank holiday hours are published.",
        "",
    ]
    return "\n".join(lines)


def _price_chunk(*names: str) -> dict[str, Any]:
    """A knowledge-base answer as the seeded calls show it: the price-list
    lines for *names* (substrings of product names)."""
    picked = [p for p in PRODUCTS if any(n.lower() in p.name.lower() for n in names)]
    text = "\n".join(
        f"- {p.name}: {p.price}."
        + (f" Showed as {p.availability} on {FETCHED_SHORT}." if p.availability else "")
        + (f" {p.note}" if p.note else "")
        for p in picked
    )
    return {
        "chunks": [{"text": text, "filename": PRICE_LIST_FILE, "similarity": 0.82}],
        "query": ", ".join(names),
        "total_results": 1,
    }


# --- the facts the agent answers from --------------------------------------

OPENING_HOURS = _week(
    *[(("09:00", "17:30"),)] * 5,
    (("09:00", "17:00"),),
    (),
    note=(
        "These are the Cork store's hours. Skibbereen: the same. Newtownards: "
        "Mon to Fri 9 to 4.30. Kilkeel: Mon to Fri 8.30 to 5, Sat 9 to 12. No "
        "Sunday or bank holiday hours published."
    ),
)

EXTRA_INFO = (
    "Delivery (chmarine.com, 8 Nov 2026), dispatched same day where possible: "
    "Ireland €7.95 under €100, free from €100. Northern Ireland €8.95 under "
    "€100, free from €100. UK (not NI): €20 up to 200, €30 from 200, free "
    "over 1,500 (as written on the site), VAT and duty included. UK islands "
    "€25 under €100, €15 from €100, free from €300. EU Near €12 to €25, free "
    "from €600; EU Mid €20 or €25, free from €400; EU Far €30 or €40, free "
    "from €400 (the site doesn't say which countries are in each zone). USA "
    "€30 or €35, free from €600; rest of world €50 or €60, free from €700; "
    "duties paid on arrival. Large or dangerous goods (masts, chain, "
    "batteries, paint) may cost extra or not ship. Report loss or damage "
    "within 2 working days. Returns: within 30 days, original condition, "
    "unopened packaging; free for standard parcels in the Republic, large "
    "items extra, prepaid from elsewhere. Start in your account: Orders, "
    "Return items, then wait for authorisation. Refunds within 3 days of "
    "receipt; faulty or wrong items exchanged or refunded in full. "
    "Lifejacket servicing: annual service, booked on 021 431 5700; prices "
    "and turnaround aren't published. Also: Xtra loyalty programme, app, "
    "gift certificates, WEEE recycling."
)

CLOSING_QUESTION_TEXT = (
    "Before you go, would you like me to connect you with a member of our team?"
)
CLOSING_OFFER = (
    "Before you end any call where the caller had a real enquiry, ask: "
    '"Before you go, would you like me to connect you with a member of our '
    'team?" If they say yes, tell them you are connecting them and use the '
    "transfer tool. If putting through isn't available, the team is closed or "
    "the transfer doesn't connect, take a message so the team calls them "
    "back. Ask it once, and not on a wrong number, a silent call or a sales "
    "call, right after taking a message or putting them through, or when "
    "you already offered to connect them on this call."
)

FACTS = {
    "business_name": NAME,
    "business_description": (
        "Irish chandlery and boat-equipment megastore, online at chmarine.com "
        "and in stores in Cork (Frankfield), Skibbereen, Newtownards and "
        "Kilkeel (KTS Sea Safety). Top brands, large stocks, best prices and "
        "technical advice: boat care, anodes, rope, watersports, lifejackets, "
        "boats, boat controls, cabin and galley, chandlery, clothing, "
        "electrical. Brands include Jabsco, Victron, International, Barton, "
        "Plastimo, Musto, MG Duff, Ocean Signal and ILCA. ISO 9001. This is "
        "the sales and support line."
    ),
    "opening_hours": "Mon–Fri 9am–5.30pm, Sat 9am–5pm, closed Sunday",
    "address": (
        "Cork: Frankfield Industrial Estate, Frankfield Road, Cork T12 KA99. "
        "Skibbereen: Nautic House, Marsh Rd, P81 R230. Newtownards: Scrabo "
        "Business Park, Jubilee Rd, Co. Down BT23 4YH. Kilkeel (KTS Sea "
        "Safety): The Harbour, Kilkeel, Co. Down BT34 4AX."
    ),
    "website": SITE,
    "extra_info": EXTRA_INFO,
}

LINE_RULES = f"""{RULES_MARKER}
Products and prices: when a caller asks about a product, a price, a size or whether we sell something, search the price list with {KB_FUNCTION} first. Quote only prices that are in it, and say they are the prices listed on chmarine.com on {FETCHED}, that prices can change, and that the website or the team confirm the final price. If a product, size or colour isn't in it, say you don't have that price and offer the website or the team; never guess or estimate a price. You can't see live stock: never say how many are in stock or promise that something is in stock; you may say what the product page showed on {FETCHED}. Never offer a discount or agree to match another shop's price: offer a member of the team.
Safety and fit: for lifejackets, buoyancy aids, beacons or anything a person's safety depends on, give only the facts in the price list and never say a product is suitable or safe for a particular person, child or boat. For a baby or young child, always say the team should check the size and fit with them, and offer to connect them.
Technical advice (which part fits an engine, wiring, how much paint a hull needs): if the price list has a matching product, name it and its listed price first; then say the exact fit or quantity needs checking and offer the team. Never guess a fit or a quantity.
Order status: use {ORDER_FUNCTION}. Ask for the order number first, then the email address or the mobile number used on the order. Read an email address back to confirm it, spelling any unusual part letter by letter. Never look an order up by name or phone number alone, and never read out details the tool didn't give. Tell the caller the status in plain words: what it is, its date, the items, the courier and the last four characters of the tracking number if given. For full tracking, point them to the dispatch email or the Orders page of their account on chmarine.com. If the tool can't verify the order, say so without suggesting which detail was wrong, and ask them to check the details once. If it still can't verify, or the tool says to stop, stop trying and offer a callback from the team: take their name, best number and the order number.
Delivery, returns and servicing: answer from the facts above. Lifejacket servicing prices and turnaround aren't published: take a message for the team to call back with them.
{{{{initial_context.{CLOSING_OFFER_KEY} | fallback:}}}}"""

CLOSING_MARKER = "Closing offer (CH Marine):"
# In the steps that talk to the caller, so the model meets the rule where it
# decides to end the call, not only in the rules at the end of the prompt.
CLOSING_STEP = (
    f"{CLOSING_MARKER} when the caller says that's all, thanks, or starts to "
    "say goodbye after a real enquiry (a product, price, stock, order, "
    "delivery, return, servicing or advice question), don't say goodbye yet. "
    f'First ask: "{CLOSING_QUESTION_TEXT}" and wait for the answer. If yes, '
    "connect them with the transfer tool (or take a message if that isn't "
    "possible). Only then say goodbye. Skip it for a wrong number, a silent "
    "caller or a sales call, when you have just taken a message or put them "
    "through, and when you already offered to connect them on this call."
)
# When the agent may end the call early ("Polite Goodbye").
END_EARLY_CONDITION = (
    "It is a wrong number, a silent call or a sales call; or the caller has "
    "what they needed, wants to go, and has already been asked whether they "
    "would like to be connected with a member of the team."
)

ADDED_FIELDS = (
    {
        "name": "product_asked_about",
        "type": "string",
        "prompt": (
            "The products the caller asked about, by brand and product name "
            "as said (e.g. Ocean Signal RescueME PLB1), separated by commas. "
            "Empty if none."
        ),
    },
    {
        "name": "order_number",
        "type": "string",
        "prompt": "The order number the caller gave, e.g. CHM-104203. Empty if none.",
    },
)


# --- sample orders (made up, marked as demo data) ---------------------------

ORDERS_NOTE = (
    "Demo data: 20 made-up orders for the CH Marine demo. The people, "
    "numbers (555 and drama-range), @example.com addresses and tracking "
    f"numbers are invented; the products and prices are from chmarine.com "
    f"on {FETCHED}, and delivery is charged by its published rates."
)


@dataclass(frozen=True)
class SampleOrder:
    number: str
    customer: str
    mobile: str
    email: str
    town: str
    country: str  # IE | NI | UK | ES
    items: tuple[
        tuple[int, str, str, str | None], ...
    ]  # qty, name, unit €, line status
    status: str
    ordered_days_ago: int
    status_days_ago: int
    courier: str | None = None
    tracking: str | None = None
    expected_in_days: int | None = None
    note: str | None = None


def _eur(value: float) -> str:
    return f"{value:.2f}"


def delivery_charge(country: str, goods: float) -> float:
    """The published rate for an order of *goods* euro (8 Nov 2026)."""
    if country == "IE":
        return 0.0 if goods >= 100 else 7.95
    if country == "NI":
        return 0.0 if goods >= 100 else 8.95
    if country == "UK":
        return 20.0 if goods < 200 else 30.0 if goods < 1500 else 0.0
    if country == "ES":
        # The site doesn't say which EU zone Spain is in; the sample Spanish
        # order is over €600, free in every EU zone.
        if goods >= 600:
            return 0.0
        raise ValueError("a Spanish sample order must be €600 or more")
    raise ValueError(country)


ORDERS: tuple[SampleOrder, ...] = (
    SampleOrder(
        "CHM-104201",
        "Aoife Murphy",
        "+353855550201",
        "aoife.murphy@example.com",
        "Cork",
        "IE",
        ((1, "Rule 1100 Bilge Pump, 12 volt", "77.95", None),),
        "received",
        0,
        0,
    ),
    SampleOrder(
        "CHM-104202",
        "Seán O'Sullivan",
        "+353875550202",
        "sean.osullivan@example.com",
        "Kinsale, Co. Cork",
        "IE",
        ((2, "International Micron 350 Antifoul, 2.5 litre", "164.95", None),),
        "processing",
        1,
        0,
    ),
    SampleOrder(
        "CHM-104203",
        "Niamh Walsh",
        "+353865550203",
        "niamh.walsh@example.com",
        "Galway",
        "IE",
        (
            (1, "Ocean Signal RescueME PLB1 Personal Locator Beacon", "349.95", None),
            (1, "Ocean Signal Flotation Pouch for RescueME PLB1", "26.95", None),
        ),
        "dispatched",
        3,
        1,
        "Courier",
        "DEMOCHM8Q4F2K",
        1,
    ),
    SampleOrder(
        "CHM-104204",
        "Conor Byrne",
        "+353835550204",
        "conor.byrne@example.com",
        "Dublin 4",
        "IE",
        ((1, "Plastimo Iris 50 hand bearing compass, blue", "89.95", None),),
        "dispatched",
        2,
        1,
        "Courier",
        "DEMOCHM3T7W9R",
        1,
    ),
    SampleOrder(
        "CHM-104205",
        "Ciara Kelly",
        "+447700900205",
        "ciara.kelly@example.com",
        "Belfast",
        "NI",
        ((2, "Plastimo Seapack Inflatable Lifejacket 150N", "73.95", None),),
        "dispatched",
        4,
        2,
        "Courier",
        "DEMOCHM5N2B8D",
        1,
    ),
    SampleOrder(
        "CHM-104206",
        "Pádraig McCarthy",
        "+353855550206",
        "padraig.mccarthy@example.com",
        "Skibbereen, Co. Cork",
        "IE",
        ((2, "MGDuff Cut Down Skeg MYA1 Anode, Yamaha and Honda", "13.95", None),),
        "delivered",
        12,
        9,
        "Courier",
        "DEMOCHM1H6K3P",
    ),
    SampleOrder(
        "CHM-104207",
        "Orla Gallagher",
        "+353875550207",
        "orla.gallagher@example.com",
        "Westport, Co. Mayo",
        "IE",
        ((1, "Victron Blue Smart IP67 Battery Charger 12V 17A", "180.95", None),),
        "delivered",
        15,
        12,
        "Courier",
        "DEMOCHM7C9M4X",
    ),
    SampleOrder(
        "CHM-104208",
        "Darragh Ryan",
        "+353865550208",
        "darragh.ryan@example.com",
        "Crosshaven, Co. Cork",
        "IE",
        ((1, "Musto Sardinia BR1 Women's Jacket 2.0, navy, size 12", "99.95", None),),
        "delivered",
        9,
        6,
        "Courier",
        "DEMOCHM2V8J6L",
    ),
    SampleOrder(
        "CHM-104209",
        "Sinéad O'Brien",
        "+353835550209",
        "sinead.obrien@example.com",
        "Dún Laoghaire, Co. Dublin",
        "IE",
        ((2, "Crewsaver Crewfit 150N ISO Automatic Lifejacket", "138.95", None),),
        "awaiting_stock",
        6,
        6,
        expected_in_days=6,
        note="Waiting for stock from the supplier; dispatched as soon as it arrives.",
    ),
    SampleOrder(
        "CHM-104210",
        "Eoin Doyle",
        "+353855550210",
        "eoin.doyle@example.com",
        "Clifden, Co. Galway",
        "IE",
        ((1, "Crewsaver Supersafe Child's Lifejacket with Harness", "89.95", None),),
        "back_ordered",
        8,
        7,
        expected_in_days=9,
        note="Back-ordered with the supplier.",
    ),
    SampleOrder(
        "CHM-104211",
        "Róisín Quinn",
        "+353875550211",
        "roisin.quinn@example.com",
        "Kilrush, Co. Clare",
        "IE",
        (
            (
                1,
                "Jabsco Amazon Universal manual bilge pump, 38mm",
                "141.95",
                "dispatched",
            ),
            (
                1,
                "Crewsaver Crewfit 150N ISO Automatic Lifejacket",
                "138.95",
                "waiting for stock",
            ),
        ),
        "partially_dispatched",
        5,
        3,
        "Courier",
        "DEMOCHM9D4R7S",
        8,
        note="The pump has gone; the lifejacket follows when it is back in stock.",
    ),
    SampleOrder(
        "CHM-104212",
        "Liam Lynch",
        "+353865550212",
        "liam.lynch@example.com",
        "Tralee, Co. Kerry",
        "IE",
        ((1, "Musto Essential Softshell Men's Jacket, navy, size L", "90.95", None),),
        "return_requested",
        14,
        2,
        note="Return requested for a different size; waiting for authorisation.",
    ),
    SampleOrder(
        "CHM-104213",
        "Mary Connolly",
        "+353835550213",
        "mary.connolly@example.com",
        "Wexford",
        "IE",
        ((1, "International Cruiser 250 Antifoul, 3 litre", "132.95", None),),
        "return_authorised",
        18,
        4,
        note="Return authorised; send it back unopened.",
    ),
    SampleOrder(
        "CHM-104214",
        "Declan Hayes",
        "+353855550214",
        "declan.hayes@example.com",
        "Bantry, Co. Cork",
        "IE",
        ((1, "Victron Blue Smart IP67 Battery Charger 12V 17A", "180.95", None),),
        "refunded",
        24,
        10,
        note="Refunded in full after the return arrived.",
    ),
    SampleOrder(
        "CHM-104215",
        "Emma Burke",
        "+353875550215",
        "emma.burke@example.com",
        "Athlone, Co. Westmeath",
        "IE",
        ((1, "Musto Women's Fenland Jacket, navy, size 14", "290.00", None),),
        "cancelled",
        11,
        11,
        note="Cancelled by the customer before dispatch; refunded.",
    ),
    SampleOrder(
        "CHM-104216",
        "Fergal Collins",
        "+447700900216",
        "fergal.collins@example.com",
        "Liverpool",
        "UK",
        (
            (1, "MGDuff Volvo Penta 290 Drive Anode Kit, zinc", "89.95", None),
            (1, "International Micron 350 Antifoul, 2.5 litre", "164.95", None),
        ),
        "dispatched",
        5,
        3,
        "International courier",
        "DEMOCHM4G1Q5Z",
        2,
    ),
    SampleOrder(
        "CHM-104217",
        "Gráinne Fitzgerald",
        "+353865550217",
        "grainne.fitzgerald@example.com",
        "Alicante, Spain",
        "ES",
        (
            (1, "Ocean Signal RescueME PLB1 Personal Locator Beacon", "349.95", None),
            (1, "Jabsco Amazon Universal manual bilge pump, 38mm", "141.95", None),
            (1, "International Micron 350 Antifoul, 2.5 litre", "164.95", None),
        ),
        "dispatched",
        6,
        4,
        "International courier",
        "DEMOCHM6X3E8U",
        3,
    ),
    SampleOrder(
        "CHM-104218",
        "Ronan Moore",
        "+447700900218",
        "ronan.moore@example.com",
        "Bangor, Co. Down",
        "NI",
        ((1, "Rule 1100 Bilge Pump, 12 volt", "77.95", None),),
        "delivered",
        10,
        7,
        "Courier",
        "DEMOCHM8L2Y4N",
    ),
    SampleOrder(
        "CHM-104219",
        "Clodagh Nolan",
        "+353835550219",
        "clodagh.nolan@example.com",
        "Cobh, Co. Cork",
        "IE",
        ((2, "Spinlock Elite Lifejacket Re-arming Kit (33g cylinder)", "36.95", None),),
        "processing",
        1,
        1,
    ),
    SampleOrder(
        "CHM-104220",
        "Brian Power",
        "+353855550220",
        "brian.power@example.com",
        "Howth, Co. Dublin",
        "IE",
        ((1, "Plastimo Iris 100 Compass, blue trim", "99.95", None),),
        "received",
        0,
        0,
    ),
)


def sample_orders(now: datetime) -> list[dict[str, Any]]:
    """The orders as stored, dated back from *now* (local date)."""
    today = now.date()
    out = []
    for o in ORDERS:
        goods = sum(q * float(price) for q, _, price, _ in o.items)
        charge = delivery_charge(o.country, goods)
        out.append(
            {
                "order_number": o.number,
                "order_date": (today - timedelta(days=o.ordered_days_ago)).isoformat(),
                "customer": o.customer,
                "mobile": o.mobile,
                "email": o.email,
                "delivery_town": o.town,
                "items": [
                    {
                        "quantity": q,
                        "name": name,
                        "unit_price": price,
                        **({"status": s} if s else {}),
                    }
                    for q, name, price, s in o.items
                ],
                "goods": _eur(goods),
                "delivery": _eur(charge),
                "total": _eur(goods + charge),
                "status": o.status,
                "status_date": (today - timedelta(days=o.status_days_ago)).isoformat(),
                "courier": o.courier,
                "tracking": o.tracking,
                "expected_date": (
                    today + timedelta(days=o.expected_in_days)
                ).isoformat()
                if o.expected_in_days is not None
                else None,
                "note": o.note,
            }
        )
    return out


# --- the calls -------------------------------------------------------------

CLOSING_QUESTION = CLOSING_QUESTION_TEXT
NO_THANKS = [
    "No, that's everything, thanks.",
    "No, you're grand, thanks a million.",
    "No thanks, that's all I needed.",
    "Ah no, that's great. Thanks.",
]
BYE = f"Thanks for calling {NAME}. Bye now."


def _kb(t: Talk, query: str, *names: str) -> None:
    t.tool(KB_FUNCTION, {"query": query}, _price_chunk(*names))


def _close(
    c: Ctx,
    t: Talk,
    *,
    captured: dict[str, str],
    summary: str,
    reason: str,
    yes_chance: float = 0.15,
    unanswered: list[str] | None = None,
) -> Plan:
    """The closing offer, then goodbye or a transfer (the live gate turns a
    transfer while closed into a message: ``fit_to_opening_hours``)."""
    t.a(CLOSING_QUESTION)
    if c.rng.random() < yes_chance:
        t.c("Actually, yes please, if someone's free.")
        t.a("No problem. One moment, I'm connecting you now.")
        answered = c.rng.random() < 0.8
        t.transfer(answered)
        if answered:
            return Plan(
                t.steps,
                TRANSFERRED,
                captured,
                f"{summary} Took the offer to speak to the team; put through.",
                reason,
                unanswered=list(unanswered or []),
                status="transfer_call",
            )
        t.a(
            "I'm sorry, the team are all busy at the moment. Can I take your "
            "name and number so someone calls you back?"
        )
        t.message()
        t.c(f"Yeah. It's {c.caller.name}, {c.number_words()}.")
        t.a(
            f"Thanks, {c.caller.first}. That's {c.number_words()}. Someone will ring you back."
        )
        t.bye(BYE)
        return Plan(
            t.steps,
            TRANSFER_NOT_ANSWERED,
            {
                **captured,
                "caller_name": c.caller.name,
                "callback_number": c.number_digits(),
            },
            f"{summary} Wanted the team; nobody picked up, left a number.",
            reason,
            unanswered=list(unanswered or []),
        )
    t.c(c.pick(NO_THANKS))
    t.bye(BYE)
    return Plan(
        t.steps,
        UNANSWERED if unanswered else HANDLED,
        captured,
        summary,
        reason,
        unanswered=list(unanswered or []),
    )


def _plb(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c("Hi, how much is the Ocean Signal rescueMe PLB1 at the moment?")
    _kb(
        t,
        "Ocean Signal RescueME PLB1 price",
        "RescueME PLB1 Personal",
        "Flotation Pouch",
    )
    t.a(
        f"The Ocean Signal RescueME PLB1, the one for Ireland registration, is "
        f"listed at €349.95 on our website as of {FETCHED}, and it showed as in "
        "stock that day. Prices can change, so the website or the team will "
        "confirm the final price."
    )
    t.c("Grand. Is there a floating pouch for it?")
    t.a(
        "There is: the Ocean Signal flotation pouch for the PLB1 is listed at €26.95, and you can add it when you order."
    )
    return _close(
        c,
        t,
        captured={
            "call_reason": "PLB1 price and flotation pouch",
            "product_asked_about": "Ocean Signal RescueME PLB1, Ocean Signal flotation pouch",
        },
        summary="Asked the price of the Ocean Signal RescueME PLB1. Told €349.95 as listed on 8 Nov, and the flotation pouch at €26.95.",
        reason="product_stock",
    )


def _lifejacket_adult(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c(
        "Hello, I'm looking for an automatic lifejacket for myself, what have you got around a hundred euro?"
    )
    _kb(t, "automatic inflatable lifejacket adult price", "Seapack", "Crewfit 150N")
    t.a(
        "From our price list, the Plastimo Seapack 150N inflatable lifejacket "
        "is €73.95 and showed as in stock on 8 November. The Crewsaver Crewfit "
        "150N automatic is €138.95, but it showed as out of stock that day. "
        "Prices can change, so the website or the team will confirm."
    )
    t.c("And do you do the servicing on them as well?")
    t.a(
        "We do annual lifejacket servicing. The prices and turnaround aren't "
        "published, so the team can give you those."
    )
    return _close(
        c,
        t,
        captured={
            "call_reason": "Adult automatic lifejacket around €100",
            "product_asked_about": "Plastimo Seapack 150N, Crewsaver Crewfit 150N",
        },
        summary="Asked about adult automatic lifejackets. Told the Plastimo Seapack 150N €73.95 and the Crewsaver Crewfit 150N €138.95 (out of stock on 8 Nov).",
        reason="product_stock",
        yes_chance=0.3,
    )


def _lifejacket_child(c: Ctx) -> Plan:
    age = c.pick(["two", "three", "four"])
    t = Talk(c.greeting)
    t.c(
        f"Hi, I need a lifejacket for my little lad, he's {age}. Which one would fit him?"
    )
    _kb(t, "child lifejacket sizes", "Supersafe", "Baltic Skipper 1280")
    t.a(
        "We list the Crewsaver Supersafe child's lifejacket with harness at "
        "€89.95 to €103.95 depending on the size, and the Baltic Skipper 1280 "
        "in baby and junior sizes at €39.95 to €47.95. For a young child the "
        "size and fit really need checking by the team, so I won't guess "
        "which one suits him."
    )
    t.c("Okay, fair enough.")
    plan = _close(
        c,
        t,
        captured={
            "call_reason": f"Lifejacket for a {age}-year-old",
            "product_asked_about": "Crewsaver Supersafe child's lifejacket, Baltic Skipper 1280",
        },
        summary=f"Asked which lifejacket fits a {age}-year-old. Gave the listed prices and said the team should check size and fit.",
        reason="product_stock",
        yes_chance=0.6,
    )
    return plan


def _anode(c: Ctx) -> Plan:
    hp = c.pick(["15", "20", "40", "60"])
    t = Talk(c.greeting)
    t.c(f"Hi, I've a Yamaha {hp} horse outboard, which anode do I need for it?")
    _kb(t, "anode Yamaha outboard", "MYA1")
    t.a(
        "Our price list has the MGDuff cut down skeg anode MYA1 for Yamaha and "
        "Honda outboards, in magnesium, at €13.95. Which one fits depends on "
        "the exact engine model, so I'd rather the team checked that with you."
    )
    t.c("Yeah, it's an older one, I'd want to be sure.")
    t.a(CLOSING_QUESTION)
    t.c("Yes please.")
    t.a("One moment, I'm connecting you now.")
    answered = c.rng.random() < 0.75
    t.transfer(answered)
    captured = {
        "call_reason": f"Anode for a Yamaha {hp} hp outboard",
        "product_asked_about": "MGDuff MYA1 anode",
    }
    if answered:
        return Plan(
            t.steps,
            TRANSFERRED,
            captured,
            f"Asked which anode fits a Yamaha {hp} hp outboard. Gave the MGDuff MYA1 at €13.95 and put them through to check the fit.",
            "technical_advice",
            status="transfer_call",
        )
    t.a(
        "I'm sorry, nobody's free just now. Can I take your name and number for a call back?"
    )
    t.message()
    t.c(f"{c.caller.name}, {c.number_words()}.")
    t.a(f"Thanks. The team will ring you on {c.number_words()} about the anode.")
    t.bye(BYE)
    return Plan(
        t.steps,
        TRANSFER_NOT_ANSWERED,
        {
            **captured,
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
        },
        f"Asked which anode fits a Yamaha {hp} hp outboard. Nobody picked up; left a number.",
        "technical_advice",
    )


def _antifoul(c: Ctx) -> Plan:
    feet = c.pick(["24", "26", "28", "32"])
    t = Talk(c.greeting)
    t.c(
        f"Hello, how much antifoul would I need for a {feet} foot yacht, and what's the Micron 350 a tin?"
    )
    _kb(
        t,
        "International Micron 350 antifoul price coverage",
        "Micron 350",
        "Cruiser 250",
    )
    t.a(
        "The International Micron 350 in 2.5 litres is listed at €164.95, and "
        "the Cruiser 250 at €49.95 for 750ml or €132.95 for 3 litres. How much "
        "your hull needs depends on the boat, and I don't have coverage "
        "figures, so the team can work that out with you."
    )
    return _close(
        c,
        t,
        captured={
            "call_reason": f"Antifoul quantity for a {feet} ft yacht",
            "product_asked_about": "International Micron 350, International Cruiser 250",
        },
        summary=f"Asked how much antifoul a {feet} ft yacht needs and the Micron 350 price. Gave listed prices; couldn't say the quantity.",
        reason="technical_advice",
        yes_chance=0.35,
        unanswered=["How much antifoul does my hull need?"],
    )


def _rope(c: Ctx) -> Plan:
    mm = c.pick(["10", "12", "14"])
    metres = c.pick(["20", "30", "40"])
    t = Talk(c.greeting)
    t.c(
        f"Hi, do you sell rope by the metre? I want about {metres} metres of {mm} mil braid for mooring lines."
    )
    _kb(t, "rope by the metre braid price", "Marlowbraid")
    t.a(
        "We do. The Marlow Marlowbraid is sold by the metre, from €1.60 to "
        "€8.45 a metre depending on the diameter. I don't have the exact price "
        f"for {mm} mil, but it's on the product page on chmarine.com, or the "
        "team can tell you."
    )
    return _close(
        c,
        t,
        captured={
            "call_reason": f"{metres} m of {mm} mm braid by the metre",
            "product_asked_about": "Marlow Marlowbraid rope",
        },
        summary=f"Asked about {metres} m of {mm} mm braid. Told Marlowbraid is €1.60 to €8.45 a metre by diameter; exact {mm} mm price is on the website.",
        reason="product_stock",
    )


def _musto(c: Ctx) -> Plan:
    size = c.pick(["10", "12", "14"])
    t = Talk(c.greeting)
    t.c(f"Hi, have you the Musto Sardinia jacket in a women's {size} in Cork?")
    _kb(t, "Musto Sardinia jacket women", "Sardinia BR1")
    t.a(
        "The Musto Sardinia BR1 women's jacket 2.0 in navy, from the Cork Week "
        "range, is listed at €99.95, down from €169. I can't see stock by size "
        "or by store, so the team would need to check a "
        f"size {size} for you."
    )
    return _close(
        c,
        t,
        captured={
            "call_reason": f"Musto Sardinia jacket, women's {size}, in Cork",
            "product_asked_about": "Musto Sardinia BR1 women's jacket",
        },
        summary=f"Asked if the Musto Sardinia BR1 women's jacket is in stock in a {size} in Cork. Gave the €99.95 price; stock needs the team.",
        reason="product_stock",
        yes_chance=0.55,
    )


def _gear(c: Ctx) -> Plan:
    ask, query, names, said, product, summary = c.pick(
        [
            (
                "What's the price of the Rule 1100 bilge pump?",
                "Rule 1100 bilge pump price",
                ("Rule 1100",),
                "The Rule 1100 bilge pump, 12 volt, is listed at €77.95 and showed as in stock on 8 November.",
                "Rule 1100 bilge pump",
                "Asked the price of the Rule 1100 bilge pump. Told €77.95 as listed.",
            ),
            (
                "Have you a manual bilge pump, a Jabsco one?",
                "Jabsco manual bilge pump",
                ("Amazon Universal",),
                "We list the Jabsco Amazon Universal manual pump, 38mm, at €141.95, and it showed as in stock on 8 November.",
                "Jabsco Amazon Universal pump",
                "Asked about a Jabsco manual bilge pump. Told the Amazon Universal at €141.95.",
            ),
            (
                "How much is the Victron Blue Smart charger, the waterproof one?",
                "Victron Blue Smart IP67 charger",
                ("Victron Blue Smart",),
                "The Victron Blue Smart IP67 charger, 12 volt 17 amp, is listed at €180.95.",
                "Victron Blue Smart IP67 charger",
                "Asked the price of the Victron Blue Smart IP67 charger. Told €180.95 as listed.",
            ),
            (
                "Do you have a hand bearing compass?",
                "hand bearing compass",
                ("Iris 50",),
                "We list the Plastimo Iris 50 hand bearing compass with night illumination, in blue, at €89.95.",
                "Plastimo Iris 50 compass",
                "Asked about a hand bearing compass. Told the Plastimo Iris 50 at €89.95.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi there. {ask}")
    _kb(t, query, *names)
    t.a(
        f"{said} Prices can change, so the website or the team confirm the final price."
    )
    return _close(
        c,
        t,
        captured={"call_reason": ask.rstrip("?"), "product_asked_about": product},
        summary=summary,
        reason="product_stock",
    )


def _delivery(c: Ctx) -> Plan:
    where, ask, said, summary, unanswered = c.pick(
        [
            (
                "Belfast",
                "What do you charge to deliver to Belfast?",
                "Delivery to Northern Ireland is €8.95 for orders under €100, and free from €100.",
                "Asked the delivery cost to Belfast. Told €8.95 under €100, free from €100.",
                None,
            ),
            (
                "Manchester",
                "Do you deliver to England, to Manchester? What does it cost?",
                "We do. To the UK outside Northern Ireland it's €20 for orders up to 200 and €30 above that, free over 1,500 as the website lists it, and VAT and duty are included.",
                "Asked about delivery to Manchester. Told the UK rates; VAT and duty included.",
                None,
            ),
            (
                "Spain",
                "I keep the boat in Spain, can you send an order there and what would it cost?",
                "We ship to the EU. Our website lists three EU zones: near, mid and far, with charges from €12 to €40 depending on the zone and the order value, and free delivery from €400 or €600. I don't have which zone Spain is in, so the team can confirm the exact cost.",
                "Asked about delivery to Spain. Gave the EU zone rates; couldn't say which zone Spain is in.",
                "Which EU delivery zone is Spain in?",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi, quick one. {ask}")
    t.a(said)
    t.c("And how quick would it go out?")
    t.a(
        "Orders are dispatched the same day where possible, and any delay is let known within 24 hours."
    )
    return _close(
        c,
        t,
        captured={"call_reason": f"Delivery cost to {where}"},
        summary=summary,
        reason="orders_delivery",
        unanswered=[unanswered] if unanswered else None,
    )


def _today_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Dublin"))


def _order(c: Ctx, number: str) -> dict[str, Any]:
    # Dated from today, as the seed stores them (not from the call's date).
    del c
    orders = {o["order_number"]: o for o in sample_orders(_today_now())}
    return orders[number]


def _number_words(number: str) -> str:
    return "C H M " + " ".join(number.split("-")[1])


def _order_status(c: Ctx) -> Plan:
    """A verified lookup: an order whose status was already reached when the
    call came in and hasn't changed since (so the call matches the data)."""
    days_ago = (_today_now().date() - c.started.date()).days
    fitting = [
        o
        for o in ORDERS
        if o.status
        in (
            "dispatched",
            "delivered",
            "awaiting_stock",
            "back_ordered",
            "partially_dispatched",
        )
        and o.status_days_ago >= days_ago
    ]
    if not fitting:
        return _order_unverified(c)
    pick = c.pick(fitting)
    order = _order(c, pick.number)
    result = demo_orders.answer(order)
    by_email = c.rng.random() < 0.5
    t = Talk(c.greeting)
    t.c("Hi, I'm ringing to see where my order is.")
    t.a("I can check that for you. What's the order number?")
    t.c(f"It's {_number_words(pick.number)}.")
    if by_email:
        local, domain = pick.email.split("@")
        t.a("Thanks. And the email address used on the order?")
        t.c(f"{local.replace('.', ' dot ')} at {domain.replace('.', ' dot ')}.")
        t.a(f"That's {local.replace('.', ' dot ')} at example dot com. Is that right?")
        t.c("That's it.")
        args = {
            "order_number": pick.number,
            "email": pick.email,
            "caller_name": pick.customer,
        }
    else:
        t.a("Thanks. And the mobile number used on the order?")
        digits = pick.mobile.replace("+353", "0").replace("+44", "0")
        spoken = f"{digits[:3]} {digits[3:6]} {digits[6:]}"
        t.c(f"{spoken}.")
        args = {
            "order_number": pick.number,
            "phone": pick.mobile,
            "caller_name": pick.customer,
        }
    t.tool(
        ORDER_FUNCTION, args, {"status": "success", "status_code": 200, "data": result}
    )
    status = pick.status
    first = pick.customer.split()[0]
    if status == "dispatched":
        said = (
            f"Thanks, {first}. Your order was dispatched on {result['status_date_spoken']} "
            f"with {pick.courier.lower()}, tracking ending {' '.join(pick.tracking[-4:])}. "
            "The full tracking link is in your dispatch email, or in Orders in your account on chmarine.com."
        )
        summary = f"Order {pick.number} verified: dispatched {result['status_date']}, tracking ending {pick.tracking[-4:]}."
    elif status == "delivered":
        said = f"Thanks, {first}. That order shows as delivered on {result['status_date_spoken']} to {pick.town.split(',')[0]}."
        summary = f"Order {pick.number} verified: delivered {result['status_date']}."
    elif status == "partially_dispatched":
        said = (
            f"Thanks, {first}. Part of that order has gone: the pump was dispatched on "
            f"{result['status_date_spoken']}, tracking ending {' '.join(pick.tracking[-4:])}. "
            f"The lifejacket is waiting for stock and is expected around {result['expected_date_spoken']}."
        )
        summary = f"Order {pick.number} verified: partly dispatched; the rest expected {result['expected_date']}."
    else:
        said = (
            f"Thanks, {first}. That order is waiting for stock from the supplier. "
            f"It's expected around {result['expected_date_spoken']} and goes out as soon as it arrives."
        )
        summary = f"Order {pick.number} verified: {result['status'].lower()}, expected {result['expected_date']}."
    t.a(said)
    return _close(
        c,
        t,
        captured={
            "call_reason": "Order status",
            "order_number": pick.number,
            "caller_name": pick.customer,
        },
        summary=summary,
        reason="orders_delivery",
        yes_chance=0.2 if status in ("awaiting_stock", "back_ordered") else 0.05,
    )


def _order_unverified(c: Ctx) -> Plan:
    """Two checks that don't match: the agent stops and takes a callback."""
    pick = c.pick(
        [o for o in ORDERS if o.status in ("dispatched", "processing", "back_ordered")]
    )
    wrong = f"{c.caller.first.lower()}{c.rng.randint(10, 99)}@example.com"
    t = Talk(c.greeting)
    t.c("Hello, I want to check on an order I placed.")
    t.a("Of course. What's the order number?")
    t.c(f"{_number_words(pick.number)}.")
    t.a("Thanks. And the email address or mobile number used on the order?")
    t.c(f"Try {wrong.split('@')[0]} at example dot com.")
    fail = demo_orders.refusal(locked=False)
    t.tool(
        ORDER_FUNCTION,
        {"order_number": pick.number, "email": wrong},
        {"status": "success", "status_code": 200, "data": fail},
    )
    t.a(
        "I couldn't verify that order with those details. Could you check the order number and the email or mobile used on the order?"
    )
    t.c("Maybe it was my work email, I'm not sure which. Try my mobile.")
    t.tool(
        ORDER_FUNCTION,
        {"order_number": pick.number, "phone": c.number_digits()},
        {
            "status": "success",
            "status_code": 200,
            "data": demo_orders.refusal(locked=True),
        },
    )
    t.a(
        "I'm sorry, I still can't verify it, so I won't try again on this call. I can have the team call you back about the order."
    )
    t.c("Yes, do that please.")
    t.message()
    t.a("What's your name?")
    t.c(c.caller.name)
    t.a("And the best number for you?")
    t.c(c.number_words())
    t.a(
        f"That's {c.number_words()}. The team will call you about order {_number_words(pick.number)}."
    )
    t.bye(BYE)
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Order status, couldn't be verified ({pick.number})",
            "order_number": pick.number,
        },
        f"Asked about order {pick.number}; the details didn't verify twice. Left a number for the team.",
        "orders_delivery",
    )


def _order_no_number(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c(
        "Hi, I ordered a few bits last week and I've heard nothing. I don't have the order number to hand."
    )
    t.a(
        "I can only look up an order with the order number and the email or "
        "mobile used on it. It's in your confirmation email. Or I can have the "
        "team call you back to look into it."
    )
    t.c("Have someone call me so.")
    t.message()
    t.a("No problem. What's your name?")
    t.c(c.caller.name)
    t.a("And the best number?")
    t.c(c.number_words())
    t.a(f"That's {c.number_words()}. The team will call you back about your order.")
    t.bye(BYE)
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": "Order status, no order number to hand",
        },
        "Wanted an update on last week's order but had no order number. Left a number for the team.",
        "orders_delivery",
    )


def _returns(c: Ctx) -> Plan:
    faulty = c.rng.random() < 0.4
    t = Talk(c.greeting)
    if faulty:
        t.c("Hi, the bilge pump I got from you isn't working at all. What do I do?")
        t.a(
            "I'm sorry about that. Faulty items are exchanged or refunded in "
            "full. The team will want to sort it with you, so I'll take your "
            "details for a call back."
        )
        t.message()
        t.a("What's your name?")
        t.c(c.caller.name)
        t.a("And the best number for you?")
        t.c(c.number_words())
        t.a(f"That's {c.number_words()}. The team will call you about the faulty pump.")
        t.bye(BYE)
        return Plan(
            t.steps,
            CALLBACK,
            {
                "caller_name": c.caller.name,
                "callback_number": c.number_digits(),
                "call_reason": "Faulty bilge pump",
                "product_asked_about": "bilge pump",
            },
            "Reported a faulty bilge pump. Told faulty items are exchanged or refunded in full; left a number.",
            "returns_faults",
        )
    t.c("Hi, I bought a jacket online and it's the wrong size. Can I send it back?")
    t.a(
        "You can. Returns are accepted within 30 days in their original "
        "condition and unopened packaging, and they're free for standard "
        "parcels within the Republic. Log in to your account, go to Orders, "
        "pick Return items, and wait for the return to be authorised before "
        "you send it."
    )
    t.c("And how long for the refund?")
    t.a("Refunds go out within 3 days of it reaching us.")
    return _close(
        c,
        t,
        captured={"call_reason": "Return a jacket, wrong size"},
        summary="Wanted to return a jacket that's the wrong size. Explained the 30-day returns and how to start one in the account.",
        reason="returns_faults",
    )


def _servicing(c: Ctx) -> Plan:
    count = c.pick(["two", "four", "six"])
    t = Talk(c.greeting)
    t.c(
        f"Hi, I'd like to book in {count} lifejackets for their annual service. How much is it and how long does it take?"
    )
    t.a(
        "We do annual lifejacket servicing. I don't have the prices or the "
        "turnaround, so I'll take your details and the team will call you to "
        "book it in."
    )
    t.message()
    t.a("What's your name?")
    t.c(c.caller.name)
    t.a("And the best number for you?")
    t.c(c.number_words())
    t.a(
        f"That's {c.number_words()}. The team will call you to book the {count} lifejackets in, with the price."
    )
    t.bye(BYE)
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Book {count} lifejackets for servicing",
            "product_asked_about": "Lifejacket servicing",
        },
        f"Wants {count} lifejackets serviced and the price and turnaround. Left a number for the team to book it.",
        "servicing",
        unanswered=["How much is lifejacket servicing and how long does it take?"],
    )


def _hours_q(c: Ctx) -> Plan:
    ask, said, summary = c.pick(
        [
            (
                "Are you open on Saturday in Skibbereen, and is it the same as Cork?",
                "Yes. Skibbereen and Cork both open Saturday 9 to 5, and Monday to Friday 9 to 5.30.",
                "Asked about Saturday hours in Skibbereen and Cork. Both 9 to 5.",
            ),
            (
                "Are you open this Sunday at all?",
                "Our stores don't publish Sunday hours, so I can't say they're open. Cork is open Monday to Friday 9 to 5.30 and Saturday 9 to 5.",
                "Asked about Sunday opening. No Sunday hours are published; gave the weekday hours.",
            ),
            (
                "What time does the Newtownards shop close?",
                "Newtownards is open Monday to Friday, 9 to 4.30.",
                "Asked when Newtownards closes. Told Monday to Friday 9 to 4.30.",
            ),
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi. {ask}")
    t.a(said)
    t.c("Great, thanks.")
    t.bye(BYE)
    return Plan(t.steps, HANDLED, {"call_reason": "Store hours"}, summary, "other")


def _trade(c: Ctx) -> Plan:
    company = c.pick(
        [
            "Harbour Boat Services",
            "Bantry Bay Marine",
            "Atlantic Moorings",
            "Lee Boatyard",
        ]
    )
    t = Talk(c.greeting)
    t.c(f"Hi, I'm with {company}. Do you do trade accounts, and what's the discount?")
    t.a(
        "I don't have the details of trade accounts or their terms, so I'll "
        "take your details and the team will come back to you."
    )
    t.message()
    t.a("Can I take your name?")
    t.c(c.caller.name)
    t.a("And your number?")
    t.c(c.number_words())
    t.a(
        f"That's {c.number_words()}. The team will call you about a trade account for {company}."
    )
    t.bye(BYE)
    return Plan(
        t.steps,
        CALLBACK,
        {
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
            "call_reason": f"Trade account for {company}",
        },
        f"Asked about a trade account and discount for {company}. Left a number for the team.",
        "other",
        unanswered=["Do you do trade accounts, and on what terms?"],
    )


def _technical(c: Ctx) -> Plan:
    t = Talk(c.greeting)
    t.c(
        "Hi, I'm fitting a Victron charger and I'm not sure how to wire it to two batteries. Is there someone who could talk me through it?"
    )
    t.a(
        "That's one for the team, so I won't guess at the wiring. One moment, I'm connecting you now."
    )
    answered = c.rng.random() < 0.8
    t.transfer(answered)
    captured = {
        "call_reason": "Wiring a Victron charger to two batteries",
        "product_asked_about": "Victron charger",
    }
    if answered:
        return Plan(
            t.steps,
            TRANSFERRED,
            captured,
            "Wanted help wiring a Victron charger to two batteries. Put through to the team.",
            "technical_advice",
            status="transfer_call",
        )
    t.a(
        "I'm sorry, nobody's free right now. Can I take your name and number for a call back?"
    )
    t.message()
    t.c(f"{c.caller.name}, {c.number_words()}.")
    t.a(f"Thanks. Someone will ring you on {c.number_words()}.")
    t.bye(BYE)
    return Plan(
        t.steps,
        TRANSFER_NOT_ANSWERED,
        {
            **captured,
            "caller_name": c.caller.name,
            "callback_number": c.number_digits(),
        },
        "Wanted help wiring a Victron charger. Nobody picked up; left a number.",
        "technical_advice",
    )


@dataclass
class ChMarineBusiness(Business):
    """A demo business with its own call-review category and extras."""

    template_category: str = "retail"
    # (organization_id, owner, workflow, now) -> the customised workflow
    customise_agent: Any = None
    before_delete: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


async def _customise_agent(*args: Any) -> Any:
    # The database side lives in its own module, loaded when the seed runs.
    from api.scripts import demo_chmarine_setup

    return await demo_chmarine_setup.customise_agent(*args)


async def _before_delete(organization_id: int) -> None:
    from api.scripts import demo_chmarine_setup

    await demo_chmarine_setup.before_delete(organization_id)


def _business() -> ChMarineBusiness:
    return ChMarineBusiness(
        slug=SLUG,
        name=NAME,
        kind="retail",
        template_name="AI Receptionist",
        opening_hours=OPENING_HOURS,
        facts=FACTS,
        # Placeholders, not CH Marine's people.
        owner_name="Ciarán Walsh",
        staff_name="Aisling Murphy",
        # The line the demo calls came in on: a 555 number, never dialled
        # (CH Marine's real Cork number is in the facts the agent reads).
        called_number="+353215550170",
        daily_calls=(3.2, 3.0, 2.8, 2.8, 3.0, 2.6, 0.7),
        hours=_hours(
            h7=0.3,
            h8=1.2,
            h9=3.5,
            h10=4,
            h11=3.8,
            h12=3,
            h13=3,
            h14=3.4,
            h15=3.2,
            h16=2.8,
            h17=1.8,
            h18=0.9,
            h19=0.6,
            h20=0.5,
            h21=0.3,
            h22=0.1,
        ),
        scenarios=[
            (8, _plb),
            (6, _lifejacket_adult),
            (5, _lifejacket_child),
            (7, _anode),
            (6, _antifoul),
            (5, _rope),
            (6, _musto),
            (7, _gear),
            (10, _delivery),
            (9, _order_status),
            (3, _order_unverified),
            (3, _order_no_number),
            (7, _returns),
            (6, _servicing),
            (5, _hours_q),
            (4, _trade),
            (4, _technical),
            (5, _silent),
        ],
        callers=_callers(SLUG, ("87", "86", "85", "83"), 70),
        closed_days=(6,),
        customise_agent=_customise_agent,
        before_delete=_before_delete,
    )


def rules_prompt(prompt: str) -> str:
    """The global prompt with this line's rules at the end, once."""
    head = prompt.split(f"\n\n{RULES_MARKER}", 1)[0]
    return f"{head}\n\n{LINE_RULES}"


def customised_definition(
    definition: dict[str, Any], *, document_uuid: str | None, order_tool_uuid: str
) -> dict[str, Any]:
    """The agent's steps with the price list, the order lookup, the extra
    captured details and the line's rules (idempotent)."""
    out = copy.deepcopy(definition)
    for node in out.get("nodes", []):
        data = node.setdefault("data", {})
        if node.get("id") == "global":
            data["prompt"] = rules_prompt(data.get("prompt") or "")
        if node.get("id") in ("start", "stage_1"):
            head = (data.get("prompt") or "").split(f"\n\n{CLOSING_MARKER}", 1)[0]
            data["prompt"] = f"{head}\n\n{CLOSING_STEP}"
        if node.get("type") in ("startCall", "agentNode"):
            if document_uuid:
                data["document_uuids"] = [document_uuid]
            tools = [u for u in data.get("tool_uuids") or [] if u != order_tool_uuid]
            data["tool_uuids"] = [*tools, order_tool_uuid]
        variables = data.get("extraction_variables")
        if isinstance(variables, list):
            names = {v.get("name") for v in variables if isinstance(v, dict)}
            for added in ADDED_FIELDS:
                if added["name"] not in names:
                    variables.append(dict(added))
    for edge in out.get("edges", []):
        if edge.get("target") == "end_early":
            edge.setdefault("data", {})["condition"] = END_EARLY_CONDITION
    return out


def definition_digest(definition: dict[str, Any]) -> str:
    import json

    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[
        :12
    ]


CHMARINE = _business()
