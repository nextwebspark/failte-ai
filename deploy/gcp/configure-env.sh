#!/usr/bin/env bash
#
# Materialise the GCP-specific settings into the app VM's .env, reading every
# credential from Secret Manager at run time. Nothing sensitive is stored in the
# repo, in an image, or in shell history.
#
# Run AFTER setup_remote.sh (which creates the base .env and the TLS cert).
#
#   ./deploy/gcp/configure-env.sh
#
# Idempotent — re-run any time to re-sync from Secret Manager.

set -euo pipefail

PROJECT="${DOGRAH_PROJECT_ID:-dograh-eu}"
REGION="${DOGRAH_REGION:-europe-west1}"
REPO="${DOGRAH_AR_REPO:-dograh}"
SQL_IP="${DOGRAH_SQL_IP:?DOGRAH_SQL_IP is required (Cloud SQL private IP)}"
BUCKET="${DOGRAH_BUCKET:-dograh-voice-audio-eu}"
# setup_remote.sh installs into a nested dograh/dograh directory.
ENV_FILE="${ENV_FILE:-$HOME/dograh/dograh/.env}"

[[ -f "$ENV_FILE" ]] || { echo "no .env at $ENV_FILE — run setup_remote.sh first" >&2; exit 1; }

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

echo "reading secrets from Secret Manager (project $PROJECT)..."
DB_PW="$(sm dograh-db-password)"
HMAC_ID="$(sm dograh-s3-hmac-access-id)"
HMAC_SECRET="$(sm dograh-s3-hmac-secret)"

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

set_key OSS_JWT_SECRET "$(sm dograh-oss-jwt-secret)"
set_key TURN_SECRET "$(sm dograh-turn-secret)"
set_key DOGRAH_DEVOPS_SECRET "$(sm dograh-devops-secret)"
set_key TELEPHONY_WS_TOKEN_SECRET "$(sm dograh-telephony-ws-token-secret)"

# Enforcement stays off until the carrier leg is proven end to end.
set_key TELEPHONY_WS_TOKEN_ENFORCE false

# Billing and email are opt-in: each is configured only when its secret exists
# in Secret Manager, so an install without them keeps working unchanged.
#   gcloud secrets create dograh-stripe-secret-key --data-file=-     # sk_test_/sk_live_
#   gcloud secrets create dograh-stripe-webhook-secret --data-file=- # whsec_ of the dashboard endpoint
#   gcloud secrets create dograh-resend-api-key --data-file=-        # re_...
sm_optional() { sm "$1" 2>/dev/null || true; }

STRIPE_KEY="$(sm_optional dograh-stripe-secret-key)"
if [[ -n "$STRIPE_KEY" ]]; then
  set_key BILLING_PROVIDER stripe
  set_key STRIPE_SECRET_KEY "$STRIPE_KEY"
  set_key STRIPE_WEBHOOK_SECRET "$(sm dograh-stripe-webhook-secret)"
  set_key STRIPE_AUTOMATIC_TAX "${DOGRAH_STRIPE_AUTOMATIC_TAX:-false}"
  if [[ -n "${DOGRAH_BILLING_SALES_CONTACT:-}" ]]; then
    set_key BILLING_SALES_CONTACT "$DOGRAH_BILLING_SALES_CONTACT"
  fi
fi

RESEND_KEY="$(sm_optional dograh-resend-api-key)"
if [[ -n "$RESEND_KEY" ]]; then
  set_key EMAIL_PROVIDER resend
  set_key RESEND_API_KEY "$RESEND_KEY"
  # Must be on a domain verified in Resend; onboarding@resend.dev only reaches
  # the Resend account owner's own address.
  set_key EMAIL_FROM "${DOGRAH_EMAIL_FROM:?DOGRAH_EMAIL_FROM is required with Resend, e.g. 'Fallcha.ai <no-reply@mail.example.com>'}"
fi

set_key ENABLE_SIGNUP true
set_key FASTAPI_WORKERS 2

# The upstream PostHog key is hardcoded in docker-compose.yaml and points at the
# Dograh project's own analytics. Off unless a key of our own is supplied.
set_key ENABLE_TELEMETRY false

chmod 600 "$ENV_FILE"
echo "done. $ENV_FILE is chmod 600."
