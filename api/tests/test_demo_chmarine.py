"""The CH Marine demo's data: calls, sample orders, price list and the
agent changes (api/scripts/demo_chmarine.py)."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from api.scripts import demo_chmarine as chm
from api.scripts.demo_businesses import Ctx, call_dates, fit_to_opening_hours
from api.services import demo_orders
from api.services.call_review.categories import reason_set
from api.services.report_cards.catalogue import Card, Pack, pack_for_template

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=ZoneInfo("Europe/Dublin"))


def _plans():
    business = chm.CHMARINE
    for index, start in enumerate(call_dates(business, NOW)):
        rng = random.Random(f"test:{index}")
        ctx = Ctx(
            rng=rng,
            caller=rng.choice(business.callers),
            started=start,
            business=business,
            greeting="Hi",
        )
        scenario = rng.choices(
            [s for _, s in business.scenarios], [w for w, _ in business.scenarios]
        )[0]
        yield fit_to_opening_hours(scenario(ctx), ctx)


def test_a_month_of_calls_filed_under_retail_reasons():
    plans = list(_plans())
    assert 60 <= len(plans) <= 110
    keys = reason_set("retail").keys
    assert all(p.reason in keys for p in plans)
    assert {p.reason for p in plans} >= {
        "product_stock",
        "orders_delivery",
        "technical_advice",
    }


def test_every_handled_enquiry_ends_with_the_closing_offer():
    for plan in _plans():
        said = [s.text for s in plan.steps if s.kind == "agent"]
        if plan.outcome in ("handled", "unanswered_question") and plan.reason in (
            "product_stock",
            "orders_delivery",
            "returns_faults",
            "technical_advice",
        ):
            assert chm.CLOSING_QUESTION in said


def test_order_lookups_in_the_calls_match_the_sample_orders():
    orders = {
        o["order_number"]: o
        for o in chm.sample_orders(datetime.now(ZoneInfo("Europe/Dublin")))
    }
    for plan in _plans():
        for step in plan.steps:
            if (
                step.kind == "tool"
                and step.function == chm.ORDER_FUNCTION
                and step.result["data"]["verified"]
            ):
                order = orders[step.arguments["order_number"]]
                check = demo_orders.check(
                    [order],
                    order_number=step.arguments["order_number"],
                    email=step.arguments.get("email"),
                    phone=step.arguments.get("phone"),
                )
                assert check.verified
                assert step.result["data"] == demo_orders.answer(order)


def test_sample_orders_follow_the_published_delivery_rates():
    orders = chm.sample_orders(NOW)
    assert len(orders) == 20
    statuses = {o["status"] for o in orders}
    assert statuses >= {
        "received",
        "processing",
        "dispatched",
        "delivered",
        "awaiting_stock",
        "back_ordered",
        "partially_dispatched",
        "return_requested",
        "return_authorised",
        "refunded",
        "cancelled",
    }
    for order in orders:
        assert order["email"].endswith("@example.com")
        assert "555" in order["mobile"] or order["mobile"].startswith("+447700900")
        goods = sum(i["quantity"] * float(i["unit_price"]) for i in order["items"])
        assert float(order["total"]) == pytest.approx(goods + float(order["delivery"]))
    assert (
        chm.delivery_charge("IE", 99.99) == 7.95 and chm.delivery_charge("IE", 100) == 0
    )
    assert chm.delivery_charge("NI", 50) == 8.95
    assert chm.delivery_charge("UK", 254.90) == 30


def test_price_list_is_dated_and_every_sampled_product_has_a_page():
    text = chm.price_list_markdown()
    assert "8 November 2026" in text and "can change" in text
    for product in chm.PRODUCTS:
        assert product.url.startswith("https://www.chmarine.com/")
        assert product.name in text


def test_facts_fit_the_setup_questions():
    assert len(chm.FACTS["business_description"]) <= 500
    assert len(chm.FACTS["address"]) <= 300
    assert len(chm.FACTS["extra_info"]) <= 1500
    assert len(chm.OPENING_HOURS.note or "") <= 200


def test_customised_definition_is_idempotent():
    definition = {
        "nodes": [
            {"id": "global", "type": "globalNode", "data": {"prompt": "Base."}},
            {
                "id": "start",
                "type": "startCall",
                "data": {
                    "tool_uuids": ["t"],
                    "extraction_variables": [{"name": "caller_name"}],
                },
            },
            {"id": "end", "type": "endCall", "data": {"extraction_variables": []}},
        ]
    }
    once = chm.customised_definition(
        definition, document_uuid="doc", order_tool_uuid="order"
    )
    twice = chm.customised_definition(
        once, document_uuid="doc", order_tool_uuid="order"
    )
    assert once == twice
    start = once["nodes"][1]["data"]
    assert start["document_uuids"] == ["doc"] and start["tool_uuids"] == ["t", "order"]
    assert [v["name"] for v in start["extraction_variables"]] == [
        "caller_name",
        "product_asked_about",
        "order_number",
    ]
    prompt = once["nodes"][0]["data"]["prompt"]
    assert prompt.count(chm.RULES_MARKER) == 1
    assert "{{initial_context.closing_offer" in prompt


def test_retail_agents_get_the_shop_report_pack():
    pack = pack_for_template("retail")
    assert pack.pack == Pack.RETAIL
    assert {
        Card.PRODUCT_ENQUIRIES,
        Card.ORDERS_DELIVERY,
        Card.RETURNS,
        Card.SERVICING_REQUESTS,
        Card.TOP_PRODUCTS,
    } <= set(pack.keys)
    assert reason_set("retail").bookings_label is None
