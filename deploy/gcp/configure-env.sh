#!/usr/bin/env bash
#
# Materialise the GCP-specific settings into the app VM's .env, reading every
# credential from Secret Manager at run time. Nothing sensitive is stored in the
# repo, in an image, or in shell history.
#
# Run AFTER setup_remote.sh (which creates the base .env and the TLS cert).
# The release-deploy install (/opt/lightmove/dograh) is root-owned, so the
# first run is:
#
#   sudo DOGRAH_SQL_IP=10.70.0.3 ./deploy/gcp/configure-env.sh
#
# Idempotent — re-run any time to re-sync from Secret Manager. deploy.sh runs
# the release's copy on every Deploy, with no variables. Keys written with
# `setting` (ENABLE_SIGNUP, EMAIL_FROM, PLATFORM_MODELS_ENABLED, ...) keep the
# value .env already has, whether set by hand or with a DOGRAH_* variable.
# Everything else is rewritten from Secret Manager and this script's defaults
# on every Deploy, so change those here, not in .env.

set -euo pipefail

PROJECT="${DOGRAH_PROJECT_ID:-dograh-eu}"
REGION="${DOGRAH_REGION:-europe-west1}"
REPO="${DOGRAH_AR_REPO:-dograh}"
BUCKET="${DOGRAH_BUCKET:-dograh-voice-audio-eu}"
# The git checkout that deploy/gcp/deploy.sh manages (README "Releases and
# deploys"). The pre-pipeline install was ~/dograh/dograh; pass ENV_FILE for it.
ENV_FILE="${ENV_FILE:-/opt/lightmove/dograh/.env}"

[[ -f "$ENV_FILE" ]] || { echo "no .env at $ENV_FILE — run setup_remote.sh first" >&2; exit 1; }

env_value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

# Cloud SQL private IP. Later runs reuse the host in DATABASE_URL (the last
# '@', since the password may contain one).
SQL_IP="${DOGRAH_SQL_IP:-$(env_value DATABASE_URL | sed -nE 's#^.*@([^@:/]+):[0-9]+/[^@]*$#\1#p')}"
SQL_IP="${SQL_IP:?DOGRAH_SQL_IP is required on the first run (Cloud SQL private IP)}"

# Secret values must never reach the deploy log, whatever root's gcloud config says.
export CLOUDSDK_CORE_LOG_HTTP=false CLOUDSDK_CORE_VERBOSITY=error

sm() { gcloud secrets versions access latest --secret="$1" --project="$PROJECT"; }

set_key() {
  local key="$1" val="$2"
  # Rewrite in place if present, else append. Values are written verbatim, so
  # they never pass through the shell again.
  if grep -q "^${key}=" "$ENV_FILE"; then
    python3 - "$ENV_FILE" "$key" "$val" <<'PY'
import sys
path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path).read().splitlines()
out = [f"{key}={val}" if l.startswith(key + "=") else l for l in lines]
open(path, "w").write("\n".join(out) + "\n")
PY
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
  echo "  set $key"
}

# setting KEY DEFAULT [OVERRIDE]: for values an operator may choose. Writes
# OVERRIDE (a DOGRAH_* variable) when given, else keeps what .env has, else
# DEFAULT.
setting() {
  local key="$1" default="$2" override="${3:-}" current
  current="$(env_value "$key")"
  set_key "$key" "${override:-${current:-$default}}"
}

unset_key() {
  local key="$1"
  grep -q "^${key}=" "$ENV_FILE" || return 0
  python3 - "$ENV_FILE" "$key" <<'PY'
import sys
path, key = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines()
out = [l for l in lines if not l.startswith(key + "=")]
open(path, "w").write("\n".join(out) + "\n")
PY
  echo "  removed $key"
}

echo "reading secrets from Secret Manager (project $PROJECT)..."
# Bare assignments, so set -e stops the script when a lookup fails: inside
# set_key's arguments it would write an empty value instead.
DB_PW="$(sm dograh-db-password)"
HMAC_ID="$(sm dograh-s3-hmac-access-id)"
HMAC_SECRET="$(sm dograh-s3-hmac-secret)"
JWT_SECRET="$(sm dograh-oss-jwt-secret)"
TURN_SECRET="$(sm dograh-turn-secret)"
DEVOPS_SECRET="$(sm dograh-devops-secret)"
WS_TOKEN_SECRET="$(sm dograh-telephony-ws-token-secret)"
for name in DB_PW HMAC_ID HMAC_SECRET JWT_SECRET TURN_SECRET DEVOPS_SECRET WS_TOKEN_SECRET; do
  [[ -n "${!name}" ]] || { echo "a required secret is empty ($name)" >&2; exit 1; }
done

echo "writing $ENV_FILE ..."
set_key ENVIRONMENT production
set_key REGISTRY "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

# NOTE: docker-compose.yaml hardcodes DATABASE_URL to the postgres container.
# This value only takes effect through deploy/gcp/docker-compose.override.yaml,
# which overrides that key. Without the overlay the app still talks to a local
# container and this line is silently ignored.
set_key DATABASE_URL "postgresql+asyncpg://dograh:${DB_PW}@${SQL_IP}:5432/dograh"

# Object storage: GCS through its S3-compatible XML API. No code change needed —
# api/services/filesystem/s3.py already honours these.
set_key ENABLE_AWS_S3 true
set_key S3_BUCKET "$BUCKET"
set_key S3_REGION "$REGION"
set_key S3_ENDPOINT_URL https://storage.googleapis.com
set_key S3_SIGNATURE_VERSION s3v4
set_key S3_ADDRESSING_STYLE virtual
set_key AWS_ACCESS_KEY_ID "$HMAC_ID"
set_key AWS_SECRET_ACCESS_KEY "$HMAC_SECRET"

set_key OSS_JWT_SECRET "$JWT_SECRET"
set_key TURN_SECRET "$TURN_SECRET"
set_key DOGRAH_DEVOPS_SECRET "$DEVOPS_SECRET"
set_key TELEPHONY_WS_TOKEN_SECRET "$WS_TOKEN_SECRET"

# Enforcement stays off until the carrier leg is proven end to end; switching
# it on in .env survives later runs.
setting TELEPHONY_WS_TOKEN_ENFORCE false

# Billing, email and Google are opt-in: each is configured only when its secret
# exists in Secret Manager, so an install without them keeps working unchanged.
# Create each secret, then let the VM's service account read it (it has no
# project-wide Secret Manager access):
#   read -rs V && printf %s "$V" | gcloud secrets create <name> --data-file=- --project=dograh-eu
#   gcloud secrets add-iam-policy-binding <name> --project=dograh-eu \
#     --member=serviceAccount:dograh-app-sa@dograh-eu.iam.gserviceaccount.com \
#     --role=roles/secretmanager.secretAccessor
# Names: dograh-stripe-secret-key (sk_test_/sk_live_), dograh-stripe-webhook-secret
# (whsec_ of the dashboard endpoint), dograh-resend-api-key (re_...),
# dograh-google-oauth-client-id / dograh-google-oauth-client-secret.
#
# sm_read NAME VAR: reads secret NAME into variable VAR (empty unless read).
# Returns 0 when read, 3 when absent (NOT_FOUND), 4 when not readable: without
# project-wide access a missing secret answers PERMISSION_DENIED ("or it may
# not exist"), the same as a missing grant. Any other error (network, quota)
# stops the script instead of quietly switching a feature off.
sm_read() {
  local err val rc=0
  err="$(mktemp)"
  val="$(gcloud secrets versions access latest --secret="$1" --project="$PROJECT" 2>"$err")" || rc=$?
  printf -v "$2" '%s' "$val"
  if (( rc == 0 )); then
    rm -f "$err"
    return 0
  elif grep -q PERMISSION_DENIED "$err"; then
    rm -f "$err"
    return 4
  elif grep -q NOT_FOUND "$err"; then
    rm -f "$err"
    return 3
  fi
  cat "$err" >&2
  rm -f "$err"
  exit 1
}

# Prints an optional secret's value, or nothing when absent or not readable.
sm_optional() {
  local value status=0
  sm_read "$1" value || status=$?
  if (( status == 4 )); then
    echo "  skipped $1: absent, or this VM's service account may not read it" >&2
  fi
  printf '%s' "$value"
}

STRIPE_KEY="$(sm_optional dograh-stripe-secret-key)"
if [[ -n "$STRIPE_KEY" ]]; then
  # A bare assignment, so set -e stops the script if the secret is missing
  # (inside set_key's arguments a failed lookup would write an empty value).
  STRIPE_WEBHOOK="$(sm dograh-stripe-webhook-secret)"
  set_key BILLING_PROVIDER stripe
  set_key STRIPE_SECRET_KEY "$STRIPE_KEY"
  set_key STRIPE_WEBHOOK_SECRET "$STRIPE_WEBHOOK"
  setting STRIPE_AUTOMATIC_TAX false "${DOGRAH_STRIPE_AUTOMATIC_TAX:-}"
  if [[ -n "${DOGRAH_BILLING_SALES_CONTACT:-}" ]]; then
    set_key BILLING_SALES_CONTACT "$DOGRAH_BILLING_SALES_CONTACT"
  fi
fi

RESEND_KEY="$(sm_optional dograh-resend-api-key)"
if [[ -n "$RESEND_KEY" ]]; then
  set_key EMAIL_PROVIDER resend
  set_key RESEND_API_KEY "$RESEND_KEY"
  # Must be on a domain verified in Resend; onboarding@resend.dev only reaches
  # the Resend account owner's own address. The default is this install's
  # sending domain, verified in Resend.
  setting EMAIL_FROM 'LightMove.ai <no-reply@mail.lightmove.ai>' "${DOGRAH_EMAIL_FROM:-}"
fi

# One Google OAuth client serves "Continue with Google" sign-in (api, .env)
# and the platform client for Calendar and Sheets (fallcha-tools, tools.env
# below), decided once for both: on with both secrets, off with neither (or
# only one), when stale values are removed. When a secret is not readable the
# script can't tell "deleted" from "grant missing", so it keeps what .env has
# rather than switching sign-in off; DOGRAH_GOOGLE=off turns it off
# explicitly. The next Deploy reads the secrets again, so to keep it off also
# delete them. The client (Google Auth Platform, this project) must list these
# redirect URIs: <PUBLIC_BASE_URL>/auth/google/callback and
# <PUBLIC_BASE_URL>/oauth/google-{calendar,sheets}/callback.
GOOGLE_ID="" GOOGLE_SECRET=""
GOOGLE_ID_STATUS=0 GOOGLE_SECRET_STATUS=0
if [[ "${DOGRAH_GOOGLE:-}" != off ]]; then
  sm_read dograh-google-oauth-client-id GOOGLE_ID || GOOGLE_ID_STATUS=$?
  sm_read dograh-google-oauth-client-secret GOOGLE_SECRET || GOOGLE_SECRET_STATUS=$?
fi
if [[ -n "$GOOGLE_ID" && -n "$GOOGLE_SECRET" ]]; then
  set_key GOOGLE_CLIENT_ID "$GOOGLE_ID"
  set_key GOOGLE_CLIENT_SECRET "$GOOGLE_SECRET"
elif (( GOOGLE_ID_STATUS == 4 || GOOGLE_SECRET_STATUS == 4 )); then
  GOOGLE_ID="$(env_value GOOGLE_CLIENT_ID)"
  GOOGLE_SECRET="$(env_value GOOGLE_CLIENT_SECRET)"
  if [[ -n "$GOOGLE_ID" && -n "$GOOGLE_SECRET" ]]; then
    echo "  Google client secrets not readable by this VM's service account:" \
      "keeping the values already in .env (DOGRAH_GOOGLE=off removes them)" >&2
  else
    GOOGLE_ID="" GOOGLE_SECRET=""
  fi
else
  if [[ -n "$GOOGLE_ID" || -n "$GOOGLE_SECRET" ]]; then
    echo "  only one of dograh-google-oauth-client-id / -secret exists:" \
      "Google sign-in and the platform Google client stay off" >&2
    GOOGLE_ID="" GOOGLE_SECRET=""
  fi
  unset_key GOOGLE_CLIENT_ID
  unset_key GOOGLE_CLIENT_SECRET
fi

# keeps_keys NAME CURRENT NEW: stops when NEW (comma-separated Fernet keys)
# drops a key CURRENT has. Stored rows encrypted with it would become
# unreadable, and every Deploy runs this script. Rotate by adding the new key in
# front; drop the old one only after re-encrypting, with one hand run using
# DOGRAH_DROP_ENCRYPTION_KEYS=true.
keeps_keys() {
  local name="$1" current="${2// /}" new="${3// /}" key
  local -a keys
  [[ -n "$current" && "${DOGRAH_DROP_ENCRYPTION_KEYS:-}" != true ]] || return 0
  IFS=, read -r -a keys <<< "$current"
  for key in "${keys[@]}"; do
    if [[ -n "$key" && ",$new," != *",$key,"* ]]; then
      echo "$name from Secret Manager drops a key in use; see keeps_keys in configure-env.sh" >&2
      exit 1
    fi
  done
}

# Workspace credentials at rest (api). Opt-in like billing: once set, never
# remove a key that encrypted stored rows (see docs/developer/environment-variables.mdx).
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
#     | gcloud secrets create dograh-credentials-encryption-keys --data-file=-
CRED_KEYS="$(sm_optional dograh-credentials-encryption-keys)"
if [[ -n "$CRED_KEYS" ]]; then
  keeps_keys CREDENTIALS_ENCRYPTION_KEYS "$(env_value CREDENTIALS_ENCRYPTION_KEYS)" "$CRED_KEYS"
  set_key CREDENTIALS_ENCRYPTION_KEYS "$CRED_KEYS"
fi

# fallcha-tools (integrations). REQUIRED: the overlay runs fallcha-tools and
# fails without these, so a missing secret stops this script (sm, not
# sm_optional). Create them once:
#   openssl rand -hex 32 | gcloud secrets create dograh-tools-internal-secret --data-file=-
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
#     | gcloud secrets create dograh-tools-encryption-keys --data-file=-
# TOOLS_INTERNAL_SECRET goes in .env (the api and the tools service share it);
# the tools-only keys go in deploy/gcp/secrets/tools.env (the overlay's env_file).
TOOLS_SECRET="$(sm dograh-tools-internal-secret)"
TOOLS_KEYS="$(sm dograh-tools-encryption-keys)"
[[ -n "$TOOLS_SECRET" && -n "$TOOLS_KEYS" ]] || {
  echo "dograh-tools-internal-secret / dograh-tools-encryption-keys are empty" >&2
  exit 1
}
set_key TOOLS_INTERNAL_SECRET "$TOOLS_SECRET"
PUBLIC_URL="$(grep -E '^PUBLIC_BASE_URL=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' || true)"
TOOLS_DIR="$(dirname "$ENV_FILE")/deploy/gcp/secrets"
TOOLS_ENV="$TOOLS_DIR/tools.env"
mkdir -p "$TOOLS_DIR"
if [[ -f "$TOOLS_ENV" ]]; then
  keeps_keys TOOLS_ENCRYPTION_KEYS \
    "$(grep -E '^TOOLS_ENCRYPTION_KEYS=' "$TOOLS_ENV" | tail -1 | cut -d= -f2- || true)" "$TOOLS_KEYS"
fi
(
  umask 077
  {
    printf 'TOOLS_ENCRYPTION_KEYS=%s\n' "$TOOLS_KEYS"
    # Empty URLs keep OAuth off; service-account connections still work. They
    # follow PUBLIC_BASE_URL; a DOGRAH_TOOLS_* override lasts until the next
    # Deploy.
    printf 'TOOLS_PUBLIC_BASE_URL=%s\n' "${DOGRAH_TOOLS_PUBLIC_BASE_URL:-$PUBLIC_URL}"
    printf 'TOOLS_UI_RETURN_URL=%s\n' "${DOGRAH_TOOLS_UI_RETURN_URL:-${PUBLIC_URL:+$PUBLIC_URL/integrations}}"
    # The Google client read above (both or neither). if/fi, not
    # `[[ … ]] && printf`: under set -e a false test would end the subshell.
    if [[ -n "$GOOGLE_ID" && -n "$GOOGLE_SECRET" ]]; then
      printf 'TOOLS_GOOGLE_CLIENT_ID=%s\n' "$GOOGLE_ID"
      printf 'TOOLS_GOOGLE_CLIENT_SECRET=%s\n' "$GOOGLE_SECRET"
    fi
  } > "$TOOLS_ENV"
)
chmod 600 "$TOOLS_ENV"
echo "  wrote $TOOLS_ENV"

setting ENABLE_SIGNUP true
setting FASTAPI_WORKERS 2

# Platform-managed models: every org runs on this project's Vertex AI, Speech
# and TTS (locations default to eu / europe-west1, see api/constants.py), with
# the VM service account's credentials, so customers pick models without
# holding keys. Existing BYOK configurations keep running until an admin saves
# the Models page. DOGRAH_PLATFORM_MODELS=false keeps the BYOK editor instead.
setting PLATFORM_MODELS_ENABLED true "${DOGRAH_PLATFORM_MODELS:-}"
setting PLATFORM_VERTEX_PROJECT_ID "$PROJECT" "${DOGRAH_PLATFORM_VERTEX_PROJECT_ID:-}"

# The upstream PostHog key is hardcoded in docker-compose.yaml and points at the
# Dograh project's own analytics. Off unless a key of our own is supplied.
set_key ENABLE_TELEMETRY false

chmod 600 "$ENV_FILE"
echo "done. $ENV_FILE is chmod 600."
