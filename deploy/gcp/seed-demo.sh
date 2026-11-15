#!/usr/bin/env bash
# Builds, refreshes or deletes the live site's demo workspace. Runs on the app
# VM as the SSH user; the "Seed demo" workflow (.github/workflows/seed-demo.yml)
# pipes it in:
#
#   gcloud compute ssh dograh-app ... \
#     --command "bash -s -- refresh 'LightMove Demo' /opt/lightmove/dograh" \
#     < deploy/gcp/seed-demo.sh
#
#   refresh  build the workspace if it isn't there, else replace its made-up
#            calls with a fresh month ending now (logins and agents are kept;
#            calls made today, e.g. test calls, are kept)
#   reset    delete the demo workspace, then build it again
#   delete   delete the demo workspace, its logins and its recordings
#
# It runs api.scripts.seed_demo_accounts inside the running api container (the
# release that is live), so it uses production's database, recordings bucket
# and speech credentials. The seed refuses anything that isn't a marked demo
# workspace, and on production refuses to run without --production,
# DEMO_ALLOW_PRODUCTION=yes, --workspace and a strong DEMO_PASSWORD.
#
# The password comes from Secret Manager (lightmove-demo-password, readable by
# the VM's service account) and reaches the container on stdin, never on a
# command line. See docs/demo-production.md.
set -euo pipefail

ACTION="${1:?action: refresh, reset or delete}"
WORKSPACE="${2:?workspace name, e.g. LightMove Demo}"
APP_DIR="${3:-/opt/lightmove/dograh}"
PROJECT="${GCP_PROJECT:-dograh-eu}"
SECRET="${DEMO_PASSWORD_SECRET:-lightmove-demo-password}"

case "$ACTION" in
  refresh) flags=() ;;
  reset) flags=(--reset) ;;
  delete) flags=(--delete) ;;
  *) echo "Unknown action '$ACTION' (refresh, reset or delete)" >&2; exit 2 ;;
esac
[[ "$WORKSPACE" =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]{1,60}$ ]] \
  || { echo "Workspace name '$WORKSPACE' has characters the seed won't take" >&2; exit 2; }

cd "$APP_DIR" || { echo "$APP_DIR not found" >&2; exit 1; }

# The seed needs the password even to delete (it never prints it).
if ! password="$(gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT" 2>/dev/null)"; then
  echo "Cannot read secret '$SECRET' in $PROJECT. Create it and grant the VM's" >&2
  echo "service account roles/secretmanager.secretAccessor (docs/demo-production.md)." >&2
  exit 1
fi
if [[ ${#password} -lt 12 ]]; then
  echo "Secret '$SECRET' must be at least 12 characters." >&2
  exit 1
fi

# The live release's api container (compose reads LIGHTMOVE_VERSION from .env).
if ! sudo docker compose ps --status running --services 2>/dev/null | grep -qx api; then
  echo "The api service isn't running in $APP_DIR." >&2
  exit 1
fi

echo "Seeding the demo workspace '$WORKSPACE' ($ACTION) on $(hostname) at $(date -u +%FT%TZ)"
# stdin carries the password only; the script reads it, then runs the seed.
printf '%s\n' "$password" | sudo docker compose exec -T \
  -e DEMO_ALLOW_PRODUCTION=yes \
  -e DEMO_TTS_CACHE=/tmp/lightmove-demo-tts \
  api sh -c 'IFS= read -r DEMO_PASSWORD && export DEMO_PASSWORD && exec python -m api.scripts.seed_demo_accounts --production --workspace "$0" "$@"' \
  "$WORKSPACE" "${flags[@]}"
unset password
echo "Done."
