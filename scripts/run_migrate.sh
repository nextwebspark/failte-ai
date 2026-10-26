#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$(dirname "${BASH_SOURCE[0]}")")" && pwd)"
ENV_FILE="$BASE_DIR/api/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a && . "$ENV_FILE" && set +a
fi

cd "$BASE_DIR"
alembic -c "$BASE_DIR/api/alembic.ini" upgrade head

# Starter agents for the Create agent gallery (see start_services_docker.sh).
python -m scripts.sync_agent_templates \
  || echo "WARNING: could not sync the starter agent templates; keeping the previous ones"
