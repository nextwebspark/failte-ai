"""Browser test calls count as phone calls only in a demo workspace."""

from sqlalchemy.dialects import postgresql

from api.db.dashboard_client import _inbound_phone_call


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_browser_calls_are_counted_only_with_the_demo_mark():
    sql = _sql(_inbound_phone_call(9, None))
    # Phone calls always; browser calls only alongside the demo mark.
    assert "'twilio'" in sql
    assert "'smallwebrtc'" in sql and "'webrtc'" in sql
    assert "organization_configurations" in sql and "'DEMO_ACCOUNT'" in sql
    assert "'textchat'" not in sql
