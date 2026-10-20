from api.services import posthog_client


class FakePostHog:
    def __init__(self):
        self.group_identify_calls = []

    def group_identify(self, *args, **kwargs):
        self.group_identify_calls.append((args, kwargs))


def test_group_identify_uses_stable_server_distinct_id(monkeypatch):
    fake_posthog = FakePostHog()
    monkeypatch.setattr(posthog_client, "get_posthog", lambda: fake_posthog)

    posthog_client.group_identify("organization", "42", {})

    _, kwargs = fake_posthog.group_identify_calls[0]
    assert kwargs["distinct_id"] == "server-group-identify"


def test_group_identify_preserves_real_distinct_id(monkeypatch):
    fake_posthog = FakePostHog()
    monkeypatch.setattr(posthog_client, "get_posthog", lambda: fake_posthog)

    posthog_client.group_identify(
        "organization",
        "42",
        {},
        distinct_id="stack-user-1",
    )

    _, kwargs = fake_posthog.group_identify_calls[0]
    assert kwargs["distinct_id"] == "stack-user-1"


def test_telemetry_off_disables_posthog_even_with_a_key(monkeypatch):
    monkeypatch.setattr(posthog_client, "ENABLE_TELEMETRY", False)
    monkeypatch.setattr(posthog_client, "POSTHOG_API_KEY", "phc_test")
    monkeypatch.setattr(posthog_client, "_posthog_client", None)

    assert posthog_client.get_posthog() is None
