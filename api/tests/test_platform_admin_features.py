"""Feature switch resolution (no database)."""

import re
from decimal import Decimal
from pathlib import Path

from api.services.platform_admin import features
from api.services.platform_admin.audit import AuditAction, json_safe

UI_FEATURES = (
    Path(__file__).resolve().parents[2] / "ui" / "src" / "config" / "features.ts"
)


def test_defaults_keep_campaigns_and_skills_off():
    assert features.defaults() == {"campaigns": False, "skills": False}


def test_defaults_match_the_ui_fallback():
    """ui/src/config/features.ts is what the app uses when the API can't be
    reached; it must agree with the API's defaults."""
    source = UI_FEATURES.read_text(encoding="utf-8")
    block = re.search(r"export const FEATURES = \{(.*?)\} as const", source, re.S)
    assert block, "FEATURES not found in features.ts"
    ui = {
        key: value == "true"
        for key, value in re.findall(
            r"^\s*(\w+):\s*(true|false),", block.group(1), re.M
        )
    }
    assert ui == features.defaults()


def test_platform_value_overrides_the_default():
    assert features.platform_values({"campaigns": True}) == {
        "campaigns": True,
        "skills": False,
    }


def test_unknown_stored_features_are_ignored():
    assert features.platform_values({"retired": True}) == features.defaults()
    assert features.effective_flags({}, {"retired": True}) == features.defaults()


def test_organisation_override_wins_both_ways():
    platform = {"campaigns": True, "skills": False}
    assert features.effective_flags(platform, {"campaigns": False, "skills": True}) == {
        "campaigns": False,
        "skills": True,
    }
    # No override: the platform value.
    assert features.effective_flags(platform, {}) == platform


def test_available_somewhere_counts_any_organisation_override():
    assert features.available_somewhere({}, []) == {"campaigns": False, "skills": False}
    assert features.available_somewhere({}, ["skills"]) == {
        "campaigns": False,
        "skills": True,
    }
    # On platform-wide: available even with no override.
    assert features.available_somewhere({"campaigns": True}, [])["campaigns"] is True
    assert features.available_somewhere({}, ["retired"]) == features.defaults()


def test_audit_details_are_json_safe():
    assert json_safe(
        {
            "amount": Decimal("1.50"),
            "action": AuditAction.FEATURE_PLATFORM_SET,
            "x": [Decimal("2")],
        }
    ) == {"amount": "1.50", "action": "feature.platform_set", "x": ["2"]}
