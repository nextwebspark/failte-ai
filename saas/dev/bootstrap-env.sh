#!/usr/bin/env bash
# Creates the local env files from upstream's templates and applies the fork's
# port remap (see saas/docs/FORK.md). Idempotent: existing files are left alone.
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

create_from_template ui/.env.example ui/.env || true

# Enforced on every run: the UI must talk to OUR backend on 8001, not the other
# Dograh deployment sitting on 8000.
sedi -E "s#^(BACKEND_URL=).*#\1http://localhost:8001#" ui/.env
sedi -E "s#^(NEXT_PUBLIC_BACKEND_URL=).*#\1http://localhost:8001#" ui/.env
echo "  ~ pointed ui/.env at http://localhost:8001"

echo
echo "Done. Review api/.env before starting the backend."
