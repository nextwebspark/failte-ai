#!/usr/bin/env bash
# Deploys one LightMove.ai release on the GCP app VM.
#
#   sudo /opt/lightmove/dograh/deploy/gcp/deploy.sh 0.2.0     # or v0.2.0
#
# Normally started by .github/workflows/deploy.yml, through remote-deploy.sh,
# as a systemd unit (so an SSH drop cannot interrupt it). Steps:
#   1. git fetch, refuse if tracked files were edited on the VM, check out tag vX.Y.Z
#   2. wait for live calls to finish (per uvicorn worker, via /health/active-calls)
#   3. pin LIGHTMOVE_VERSION in .env, pull the release images, `compose up -d`
#   4. wait until api, ui and fallcha-tools are healthy and the api reports X.Y.Z
#   5. on any failure after the switch: put the previous version back, exit 1
#
# The api runs `alembic upgrade head` on start. Rolling back restores the old
# images but never reverses a migration, so releases must keep migrations
# backward compatible (or be rolled forward instead).
set -euo pipefail

APP_DIR="${LIGHTMOVE_APP_DIR:-/opt/lightmove/dograh}"
DRAIN_MAX_WAIT="${DRAIN_MAX_WAIT:-600}"     # seconds to wait for live calls
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-420}"     # seconds for the stack to come up
RELEASE_SERVICES=(api ui fallcha-tools)

log() { printf '[deploy %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

# `git checkout` below rewrites this very file, and bash reads scripts
# incrementally. Run from a private copy so the checkout cannot change the
# code mid-run.
if [[ -z "${LIGHTMOVE_DEPLOY_COPY:-}" ]]; then
  copy="$(mktemp /tmp/lightmove-deploy.XXXXXX)"
  cp "$0" "$copy"
  LIGHTMOVE_DEPLOY_COPY="$copy" exec bash "$copy" "$@"
fi
trap 'rm -f "$LIGHTMOVE_DEPLOY_COPY"' EXIT

[[ $EUID -eq 0 ]] || fail "run as root (sudo)"
[[ $# -eq 1 ]] || fail "usage: deploy.sh <version>   e.g. deploy.sh 0.2.0"
VERSION="${1#v}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version must be X.Y.Z, got '$1'"
TAG="v$VERSION"

cd "$APP_DIR" || fail "$APP_DIR not found"
[[ -f .env ]] || fail "$APP_DIR/.env not found"
# Without the overlay, compose starts an empty local Postgres instead of
# using Cloud SQL — never deploy like that.
grep -q '^COMPOSE_FILE=.*deploy/gcp/docker-compose.override.yaml' .env \
  || fail ".env must set COMPOSE_FILE=docker-compose.yaml:deploy/gcp/docker-compose.override.yaml"
grep -q '^COMPOSE_PROFILES=.*remote' .env || fail ".env must set COMPOSE_PROFILES=remote"

env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '"' || true; }
env_set() {
  if grep -qE "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

# ---------------------------------------------------------------------------
# 1. Code: check out the release tag.
# ---------------------------------------------------------------------------
log "fetching tags"
git fetch --quiet --tags --force origin
git rev-parse --quiet --verify "refs/tags/$TAG" >/dev/null || fail "tag $TAG not found on origin"

# Hand edits to tracked files would be silently overwritten by the checkout.
# Changes go through the repo and a release instead.
# Submodules are ignored: the VM runs prebuilt images, and `git checkout` does
# not move the pipecat pointer, which would otherwise read as an edit.
if ! git diff --quiet --ignore-submodules HEAD --; then
  git status --short --untracked-files=no --ignore-submodules
  fail "tracked files were edited on the VM (above). Commit them to the repo or discard them, then redeploy."
fi

PREV_VERSION="$(env_get LIGHTMOVE_VERSION)"
PREV_REF="$(git rev-parse HEAD)"
log "current: ${PREV_VERSION:-none} ($(git describe --tags --always HEAD)), target: $VERSION"

git checkout --quiet --detach "$TAG"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# The overlay requires LIGHTMOVE_VERSION. Every compose call names the version
# that is running right now, so they also work on the first deploy, before
# .env has it. Passed per command, never exported: an exported value would
# override the .env value that switch_to writes.
ACTIVE_VERSION="${PREV_VERSION:-$VERSION}"
dc() { LIGHTMOVE_VERSION="$ACTIVE_VERSION" docker compose "$@"; }

api_running() { [[ -n "$(dc ps -q --status running api 2>/dev/null)" ]]; }

# Prints the total live calls across the api container's uvicorn workers
# (one process per port from 8000, see scripts/start_services_docker.sh),
# or ERR when a worker cannot be read.
active_calls() {
  dc exec -T api python - <<'PY' 2>/dev/null || echo ERR
import json, os, urllib.request
secret = os.environ.get("DOGRAH_DEVOPS_SECRET", "")
total = 0
for i in range(int(os.environ.get("FASTAPI_WORKERS", "1"))):
    req = urllib.request.Request(
        f"http://127.0.0.1:{8000 + i}/api/v1/health/active-calls",
        headers={"X-Dograh-Devops-Secret": secret},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        total += json.load(r)["active_calls"]
print(total)
PY
}

drain_calls() {
  if ! api_running; then
    log "api not running — nothing to drain"
    return
  fi
  local deadline=$(( $(date +%s) + DRAIN_MAX_WAIT )) count
  while (( $(date +%s) < deadline )); do
    count="$(active_calls)"
    if [[ "$count" == "0" ]]; then
      log "no live calls"
      return
    fi
    # ERR is treated as busy: an unreadable count must not cut a call.
    log "live calls: $count — waiting"
    sleep 10
  done
  log "WARNING: calls still live after ${DRAIN_MAX_WAIT}s — deploying anyway"
}

container_health() {
  local id
  id="$(dc ps -q "$1" 2>/dev/null)"
  [[ -n "$id" ]] || { echo missing; return; }
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id"
}

api_version() {
  dc exec -T api python -c \
    "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=5))['version'])" \
    2>/dev/null || true
}

wait_healthy() {
  local want="$1" deadline=$(( $(date +%s) + HEALTH_TIMEOUT )) svc states ok
  while (( $(date +%s) < deadline )); do
    ok=1 states=""
    for svc in "${RELEASE_SERVICES[@]}"; do
      local h
      h="$(container_health "$svc")"
      states+="$svc=$h "
      [[ "$h" == "healthy" ]] || ok=0
    done
    if (( ok )) && [[ "$(api_version)" == "$want" ]]; then
      log "healthy: ${states}version=$want"
      return 0
    fi
    log "waiting: $states"
    sleep 10
  done
  log "not healthy after ${HEALTH_TIMEOUT}s: $states api version='$(api_version)'"
  dc ps || true
  dc logs --tail 80 api || true
  return 1
}

# Returns compose up's status, but always restarts nginx: health, not the
# exit code, decides success (up also fails when a dependency is unhealthy).
switch_to() {
  local rc=0
  ACTIVE_VERSION="$1"
  env_set LIGHTMOVE_VERSION "$1"
  dc up -d --remove-orphans || rc=$?
  # nginx resolves the api container's IP once; a recreated api gets a new one.
  dc restart nginx || rc=$?
  return "$rc"
}

rollback() {
  if [[ -z "$PREV_VERSION" ]]; then
    log "no previous version recorded — cannot roll back"
    return
  fi
  log "ROLLING BACK to $PREV_VERSION"
  git checkout --quiet --detach "$PREV_REF"
  switch_to "$PREV_VERSION" || log "compose reported errors while rolling back"
  if wait_healthy "$PREV_VERSION"; then
    log "rolled back to $PREV_VERSION"
  else
    log "ROLLBACK ALSO UNHEALTHY — needs a human"
  fi
}

# ---------------------------------------------------------------------------
# 2-3. Pull first (nothing restarts if an image is missing), drain, switch.
# ---------------------------------------------------------------------------
log "pulling images for $VERSION"
if ! LIGHTMOVE_VERSION="$VERSION" docker compose pull --quiet "${RELEASE_SERVICES[@]}"; then
  git checkout --quiet --detach "$PREV_REF"
  fail "image pull failed — nothing was changed"
fi

drain_calls

log "switching to $VERSION"
switch_to "$VERSION" || log "compose reported errors — checking health anyway"
if ! wait_healthy "$VERSION"; then
  rollback
  fail "deploy of $VERSION failed"
fi

# ---------------------------------------------------------------------------
# 4. Keep the disk in check: drop release images other than current/previous.
# ---------------------------------------------------------------------------
registry="$(env_get REGISTRY)"
if [[ -n "$registry" ]]; then
  keep="${VERSION//./\\.}"
  [[ -n "$PREV_VERSION" ]] && keep+="|${PREV_VERSION//./\\.}"
  docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E "^${registry}/(dograh-api|dograh-ui|fallcha-tools):" \
    | grep -vE ":(${keep})$" \
    | xargs -r docker rmi >/dev/null 2>&1 || true
fi
docker image prune -f >/dev/null 2>&1 || true

log "deployed $VERSION (previous: ${PREV_VERSION:-none})"
