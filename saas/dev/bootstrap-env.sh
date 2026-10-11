#!/usr/bin/env bash
# Creates the local env files from upstream's templates and applies the fork's
# port remap (see saas/docs/FORK.md). Idempotent: existing files are left alone,
# except that missing integration secrets (CREDENTIALS_ENCRYPTION_KEYS,
# TOOLS_INTERNAL_SECRET, TOOLS_ENCRYPTION_KEYS) are generated; values already
# set are never overwritten.
#
#   bash saas/dev/bootstrap-env.sh
#
# Why the remap: a separate Dograh deployment on this machine holds 5432, 6379,
# 9000/9001 and 8000. The fork runs alongside it on 5433, 6380, 9002/9003, 8001.

set -euo pipefail

cd "$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")"

# in-place sed that works on both BSD (macOS) and GNU sed
sedi() { sed -i '' "$@" 2>/dev/null || sed -i "$@"; }

create_from_template() {
  local src="$1" dst="$2"
  if [[ -f "$dst" ]]; then
    echo "  = $dst already exists, leaving untouched"
    return 1
  fi
  cp "$src" "$dst"
  echo "  + created $dst"
  return 0
}

# Rewrites only the host:port portion of each URL, preserving the database name
# and redis db index from the template. This matters: api/.env.test deliberately
# targets a SEPARATE database (`test_db`) so pytest never clobbers dev data —
# blindly overwriting DATABASE_URL would point the test suite at the dev DB.
remap_ports() {
  local f="$1"
  sedi -E "s#(postgres:postgres@localhost):5432#\1:5433#" "$f"
  sedi -E "s#(redissecret@localhost):6379#\1:6380#" "$f"
  sedi -E "s#localhost:9000#localhost:9002#g" "$f"
  sedi -E "s#localhost:9001#localhost:9003#g" "$f"
  sedi -E "s#^(BACKEND_API_ENDPOINT=).*#\1\"http://localhost:8001\"#" "$f"
  echo "  ~ remapped datastore ports in $f"
}

echo "Environment files:"
if create_from_template api/.env.example api/.env; then
  remap_ports api/.env
  # OSS_JWT_SECRET is required for the local auth provider.
  if grep -q '^OSS_JWT_SECRET=' api/.env; then
    sedi -E "s#^(OSS_JWT_SECRET=).*#\1\"$(openssl rand -hex 32)\"#" api/.env
  else
    echo "OSS_JWT_SECRET=\"$(openssl rand -hex 32)\"" >> api/.env
  fi
  echo "  ~ generated OSS_JWT_SECRET"
fi

if create_from_template api/.env.test.example api/.env.test; then
  remap_ports api/.env.test
fi

# Enforced on every run, including pre-existing files.
#
# The dev launcher reads UVICORN_BASE_PORT (scripts/start_services_dev.sh:39),
# NOT UVICORN_PORT, and sources api/.env before reading it. Without this the
# backend tries to bind 8000 — which the other Dograh deployment on this machine
# already holds — and dies with "[Errno 48] Address already in use" while the
# launcher's health check happily passes against the OTHER stack's /health.
if grep -q '^UVICORN_BASE_PORT=' api/.env; then
  sedi -E "s#^(UVICORN_BASE_PORT=).*#\18001#" api/.env
else
  echo 'UVICORN_BASE_PORT=8001' >> api/.env
fi
sedi -E "/^UVICORN_PORT=/d" api/.env
echo "  ~ pinned UVICORN_BASE_PORT=8001 in api/.env"

# Fernet key: 32 random bytes, URL-safe base64 (no python needed).
fernet_key() { openssl rand -base64 32 | tr '+/' '-_'; }

# Prints the value of KEY in FILE (quotes stripped), empty when absent.
env_value() {
  grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/' || true
}

# Sets KEY=VALUE in FILE only when KEY is absent or empty; never overwrites.
ensure_key() {
  local f="$1" key="$2" value="$3"
  if [[ -n "$(env_value "$f" "$key")" ]]; then
    return 0
  fi
  if grep -qE "^$key=" "$f"; then
    sedi -E "s#^($key=).*#\1\"$value\"#" "$f"
  else
    echo "$key=\"$value\"" >> "$f"
  fi
  echo "  ~ set $key in $f"
}

# Integrations and credential encryption (enforced on every run; existing
# values are kept). The api and the tools service must share one
# TOOLS_INTERNAL_SECRET, so tools/.env takes it from api/.env.
ensure_key api/.env CREDENTIALS_ENCRYPTION_KEYS "$(fernet_key)"
ensure_key api/.env TOOLS_INTERNAL_SECRET "$(openssl rand -hex 32)"
ensure_key api/.env TOOLS_SERVICE_URL "http://localhost:8010"

if create_from_template tools/.env.example tools/.env; then
  remap_ports tools/.env
fi
ensure_key tools/.env TOOLS_ENCRYPTION_KEYS "$(fernet_key)"
ensure_key tools/.env TOOLS_INTERNAL_SECRET "$(env_value api/.env TOOLS_INTERNAL_SECRET)"
if [[ "$(env_value api/.env TOOLS_INTERNAL_SECRET)" != "$(env_value tools/.env TOOLS_INTERNAL_SECRET)" ]]; then
  echo "  ! TOOLS_INTERNAL_SECRET differs between api/.env and tools/.env; make them equal"
fi
# They hold secrets: owner-only.
chmod 600 api/.env tools/.env

create_from_template ui/.env.example ui/.env || true

# Enforced on every run: the UI must talk to OUR backend on 8001, not the other
# Dograh deployment sitting on 8000.
sedi -E "s#^(BACKEND_URL=).*#\1http://localhost:8001#" ui/.env
sedi -E "s#^(NEXT_PUBLIC_BACKEND_URL=).*#\1http://localhost:8001#" ui/.env
echo "  ~ pointed ui/.env at http://localhost:8001"

echo
echo "Done. Review api/.env before starting the backend."
