import pytest

from api.constants import _get_version


def test_app_version_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    # Release images set APP_VERSION (deploy/gcp/cloudbuild.yaml build arg).
    monkeypatch.setenv("APP_VERSION", "0.3.1")
    assert _get_version() == "0.3.1"


def test_app_version_falls_back_to_pyproject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_VERSION", raising=False)
    version = _get_version()
    assert version and version != "dev"
