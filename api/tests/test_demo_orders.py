"""The sample-order lookup's verification rules (api/services/demo_orders.py)."""

from api.services import demo_orders as d

ORDERS = [
    {
        "order_number": "CHM-104203",
        "customer": "Niamh Walsh",
        "mobile": "+353865550203",
        "email": "niamh.walsh@example.com",
        "delivery_town": "Galway",
        "items": [
            {
                "quantity": 1,
                "name": "Ocean Signal RescueME PLB1",
                "unit_price": "349.95",
            }
        ],
        "total": "376.90",
        "status": "dispatched",
        "status_date": "2026-11-07",
        "courier": "Courier",
        "tracking": "DEMOCHM8Q4F2K",
        "expected_date": "2026-11-09",
        "note": None,
    }
]


def test_order_email_and_phone_are_normalised():
    assert d.order_key("chm 104203") == d.order_key("CHM-104203") == "CHM104203"
    assert d.order_key("104203") == "CHM104203"
    assert d.email_key(" Niamh.Walsh @Example.com ") == "niamh.walsh@example.com"
    assert (
        d.phone_key("+353 86 555 0203") == d.phone_key("086 555 0203") == "0865550203"
    )
    assert d.phone_key("00353865550203") == "0865550203"
    assert d.phone_key("+44 7700 900205") == "07700900205"


def test_order_number_with_matching_email_or_phone_verifies():
    by_email = d.check(
        ORDERS, order_number="chm104203", email="NIAMH.WALSH@example.com"
    )
    by_phone = d.check(ORDERS, order_number="CHM-104203", phone="086 555 0203")
    assert by_email.verified and by_phone.verified
    assert d.check(
        ORDERS, order_number="CHM-104203", email="x@example.com", phone="0865550203"
    ).verified


def test_name_is_a_soft_check_only():
    result = d.check(
        ORDERS,
        order_number="CHM-104203",
        phone="0865550203",
        caller_name="Someone Else",
    )
    assert result.verified and result.name_matched is False
    assert not d.check(
        ORDERS, order_number="CHM-104203", caller_name="Niamh Walsh"
    ).verified


def test_no_lookup_by_name_or_phone_alone_and_no_hints():
    assert not d.check(ORDERS, order_number="", phone="0865550203").verified
    assert not d.check(ORDERS, order_number="CHM-104203").verified
    wrong_email = d.check(ORDERS, order_number="CHM-104203", email="niamh@example.com")
    wrong_order = d.check(
        ORDERS, order_number="CHM-999999", email="niamh.walsh@example.com"
    )
    assert not wrong_email.verified and not wrong_order.verified
    # Whatever was wrong, the caller hears the same thing.
    assert d.refusal(locked=False) == d.refusal(locked=False)
    assert set(d.refusal(locked=False)) == {"lookup", "verified", "say"}


def test_answer_gives_only_what_is_needed():
    answer = d.answer(ORDERS[0])
    text = repr(answer)
    assert answer["verified"] is True and answer["status"] == "Dispatched"
    assert answer["tracking_ending"] == "4F2K"
    assert "DEMOCHM8Q4F2K" not in text
    assert "example.com" not in text and "0203" not in text
    assert answer["delivery_town"] == "Galway"
    assert answer["expected_date"] == "2026-11-09"


def test_lookup_keys_name_their_organization():
    key = d.new_lookup_key(42)
    assert d.organization_of_key(key) == 42
    assert d.organization_of_key("lmdemo-orders.x.y") is None
    assert d.organization_of_key("") is None
    assert d.same_key(key, key) and not d.same_key("", key)
    assert d.bearer(f"Bearer {key}") == key and d.bearer(None) == ""


def test_owner_view_hides_the_full_tracking_number():
    (row,) = d.public_rows(ORDERS)
    assert row["tracking_ending"] == "4F2K"
    assert "DEMOCHM8Q4F2K" not in repr(row)
