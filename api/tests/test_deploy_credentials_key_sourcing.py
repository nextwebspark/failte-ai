"""Where deploy scripts take CREDENTIALS_ENCRYPTION_KEYS from.

Losing or silently replacing that key makes every encrypted secret in the
database unreadable, so ``deploy/gcp/configure-env.sh`` must never pick one
of two different keys on its own, nor invent a key for a database that may
already hold data. It runs here against a temporary ``.env`` with a fake
``gcloud`` on PATH whose Secret Manager is a directory of files.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

REPO = Path(__file__).resolve().parents[2]
CONFIGURE_ENV = REPO / "deploy" / "gcp" / "configure-env.sh"
SETUP_COMMON = REPO / "scripts" / "lib" / "setup_common.sh"
SECRET = "dograh-credentials-encryption-keys"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="needs bash to run the deploy scripts"
)

# Secret Manager: <sm>/<name> holds a value, <sm>/<name>.denied makes it
# unreadable (PERMISSION_DENIED), anything else is NOT_FOUND. ``secrets
# create`` writes <sm>/<name> unless FAKE_SM_CREATE_DENIED is set.
FAKE_GCLOUD = """#!/usr/bin/env bash
set -eu
sm="$FAKE_SM"
if [[ "$1 $2" == "secrets versions" ]]; then
  for arg in "$@"; do
    case "$arg" in --secret=*) name="${arg#--secret=}" ;; esac
  done
  if [[ -f "$sm/$name" ]]; then cat "$sm/$name"; exit 0; fi
  if [[ -f "$sm/$name.denied" ]]; then echo "PERMISSION_DENIED: $name" >&2; exit 1; fi
  echo "NOT_FOUND: $name" >&2; exit 1
fi
if [[ "$1 $2" == "secrets create" ]]; then
  [[ -z "${FAKE_SM_CREATE_DENIED:-}" ]] || { echo PERMISSION_DENIED >&2; exit 1; }
  cat > "$sm/$3"; exit 0
fi
echo "fake gcloud: unexpected $*" >&2; exit 2
"""

REQUIRED_SECRETS = {
    "dograh-db-password": "pw",
    "dograh-s3-hmac-access-id": "id",
    "dograh-s3-hmac-secret": "hmac",
    "dograh-oss-jwt-secret": "jwt",
    "dograh-turn-secret": "turn",
    "dograh-devops-secret": "devops",
    "dograh-tools-internal-secret": "tools-internal",
    "dograh-tools-encryption-keys": Fernet.generate_key().decode(),
}

SM_KEY = Fernet.generate_key().decode()
ENV_KEY = Fernet.generate_key().decode()


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.sm = tmp_path / "sm"
        self.sm.mkdir()
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gcloud = bin_dir / "gcloud"
        gcloud.write_text(FAKE_GCLOUD)
        gcloud.chmod(gcloud.stat().st_mode | stat.S_IEXEC)
        self.path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        for name, value in REQUIRED_SECRETS.items():
            (self.sm / name).write_text(value)
        self.env_file = tmp_path / ".env"
        self.env_file.write_text("PUBLIC_BASE_URL=https://app.example.com\n")

    def sm_key(self, value: str) -> None:
        (self.sm / SECRET).write_text(value)

    def env_key(self, value: str) -> None:
        with self.env_file.open("a") as f:
            f.write(f"CREDENTIALS_ENCRYPTION_KEYS={value}\n")

    def run(self, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": self.path,
            "HOME": str(self.root),
            "FAKE_SM": str(self.sm),
            "ENV_FILE": str(self.env_file),
            "DOGRAH_SQL_IP": "10.0.0.3",
            "DOGRAH_GOOGLE": "off",
            **extra,
        }
        return subprocess.run(
            ["bash", str(CONFIGURE_ENV)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def key_in_env(self) -> str | None:
        values = [
            line.split("=", 1)[1]
            for line in self.env_file.read_text().splitlines()
            if line.startswith("CREDENTIALS_ENCRYPTION_KEYS=")
        ]
        assert len(values) <= 1
        return values[0] if values else None

    def backups(self) -> list[Path]:
        return sorted(self.root.glob(".env.bak.*"))


@pytest.fixture
def gcp(tmp_path) -> Env:
    return Env(tmp_path)


def _ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stderr


def test_secret_manager_only(gcp):
    gcp.sm_key(SM_KEY)
    _ok(gcp.run())
    assert gcp.key_in_env() == SM_KEY


def test_env_only_is_kept_with_a_warning(gcp):
    gcp.env_key(ENV_KEY)
    result = gcp.run()
    _ok(result)
    assert gcp.key_in_env() == ENV_KEY
    assert "keeping CREDENTIALS_ENCRYPTION_KEYS from .env" in result.stderr


def test_env_only_when_secret_is_not_readable(gcp):
    (gcp.sm / f"{SECRET}.denied").write_text("")
    gcp.env_key(ENV_KEY)
    _ok(gcp.run())
    assert gcp.key_in_env() == ENV_KEY


def test_both_equal(gcp):
    gcp.sm_key(SM_KEY)
    gcp.env_key(SM_KEY)
    _ok(gcp.run())
    assert gcp.key_in_env() == SM_KEY


def test_both_differ_refuses_and_leaves_env_untouched(gcp):
    gcp.sm_key(SM_KEY)
    gcp.env_key(ENV_KEY)
    before = gcp.env_file.read_text()
    result = gcp.run()
    assert result.returncode == 1
    assert "DOGRAH_CREDENTIALS_KEYS_OVERRIDE" in result.stderr
    assert gcp.env_file.read_text() == before
    # Neither key is ever printed.
    assert SM_KEY not in result.stdout + result.stderr
    assert ENV_KEY not in result.stdout + result.stderr


@pytest.mark.parametrize(("override", "expected"), [("sm", SM_KEY), ("env", ENV_KEY)])
def test_both_differ_with_override(gcp, override, expected):
    gcp.sm_key(SM_KEY)
    gcp.env_key(ENV_KEY)
    _ok(gcp.run(DOGRAH_CREDENTIALS_KEYS_OVERRIDE=override))
    assert gcp.key_in_env() == expected
    # The replaced value survives in the backup.
    [backup] = gcp.backups()
    assert f"CREDENTIALS_ENCRYPTION_KEYS={ENV_KEY}" in backup.read_text()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_none_refuses_without_generate_flag(gcp):
    before = gcp.env_file.read_text()
    result = gcp.run()
    assert result.returncode == 1
    assert "DOGRAH_GENERATE_CREDENTIALS_KEY=1" in result.stderr
    assert gcp.env_file.read_text() == before
    assert not (gcp.sm / SECRET).exists()


def test_none_generates_with_flag_and_stores_it_in_secret_manager(gcp):
    _ok(gcp.run(DOGRAH_GENERATE_CREDENTIALS_KEY="1"))
    key = gcp.key_in_env()
    assert key and (gcp.sm / SECRET).read_text() == key
    Fernet(key.encode())  # a valid key


def test_generated_key_kept_in_env_when_secret_cannot_be_created(gcp):
    result = gcp.run(DOGRAH_GENERATE_CREDENTIALS_KEY="1", FAKE_SM_CREATE_DENIED="1")
    _ok(result)
    assert gcp.key_in_env()
    assert "exists ONLY in" in result.stderr
    assert not (gcp.sm / SECRET).exists()


# -- scripts/lib/setup_common.sh (OSS remote installs) -----------------------------


def _sync_remote_env(env_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            f'. "{SETUP_COMMON}" && dograh_sync_remote_env_file "$1"',
            "sync",
            str(env_file),
        ],
        env={"PATH": os.environ["PATH"], "HOME": str(env_file.parent)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _remote_env(tmp_path: Path, extra: str = "") -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PUBLIC_BASE_URL=https://203-0-113-10.sslip.io\n"
        "PUBLIC_HOST=203-0-113-10.sslip.io\n"
        "SERVER_IP=203.0.113.10\n" + extra
    )
    return env_file


def _keys(env_file: Path) -> list[str]:
    return [
        line.split("=", 1)[1]
        for line in env_file.read_text().splitlines()
        if line.startswith("CREDENTIALS_ENCRYPTION_KEYS=")
    ]


@pytest.mark.parametrize("missing", ["", "CREDENTIALS_ENCRYPTION_KEYS=\n"])
def test_remote_sync_generates_credentials_key_once(tmp_path, missing):
    env_file = _remote_env(tmp_path, missing)
    result = _sync_remote_env(env_file)
    assert result.returncode == 0, result.stderr
    [key] = _keys(env_file)
    Fernet(key.encode())
    assert _sync_remote_env(env_file).returncode == 0
    assert _keys(env_file) == [key]


def test_remote_sync_never_overwrites_credentials_key(tmp_path):
    env_file = _remote_env(tmp_path, f"CREDENTIALS_ENCRYPTION_KEYS={ENV_KEY}\n")
    result = _sync_remote_env(env_file)
    assert result.returncode == 0, result.stderr
    assert _keys(env_file) == [ENV_KEY]
