#!/usr/bin/env bash
#
# Idempotent GCP bootstrap for a Dograh deployment in europe-west1.
#
# Every step checks before it creates, so re-running is safe and is the intended
# way to converge drift. Nothing here is destructive.
#
#   ./bootstrap.sh            # show what would run, change nothing
#   ./bootstrap.sh apply      # actually create resources (BILLABLE)
#   ./bootstrap.sh apply net  # run a single step
#
# Steps: project apis ips firewall storage sql registry schedule ci
#
# See README.md for the full runbook and what each resource is for.

set -euo pipefail

# --- Configuration -----------------------------------------------------------
PROJECT_ID="${DOGRAH_PROJECT_ID:-dograh-eu}"
BILLING_ACCOUNT="${DOGRAH_BILLING_ACCOUNT:-015B77-B44E1A-20ED53}"
REGION="${DOGRAH_REGION:-europe-west1}"
ZONE="${DOGRAH_ZONE:-europe-west1-b}"

BUCKET="${DOGRAH_BUCKET:-dograh-voice-audio-eu}"
SQL_INSTANCE="${DOGRAH_SQL_INSTANCE:-dograh-pg}"
SQL_TIER="${DOGRAH_SQL_TIER:-db-g1-small}"
SQL_VERSION="${DOGRAH_SQL_VERSION:-POSTGRES_17}"
AR_REPO="${DOGRAH_AR_REPO:-dograh}"

STORAGE_SA="dograh-storage"

# GitHub Actions identity for .github/workflows/release.yml and deploy.yml.
GITHUB_REPO="${DOGRAH_GITHUB_REPO:-nextwebspark/failte-ai}"
DEPLOY_SA="github-deployer"
BUILD_SA="lightmove-build"
WIF_POOL="github"
WIF_PROVIDER="github-oidc"
APP_VM="${DOGRAH_APP_VM:-dograh-app}"

# Carrier signalling addresses allowed to reach SIP/RTP on the sip VM.
# 84.39.233.90 is the only VoIPTel address confirmed responding on 5071.
# Widen this the moment they send the full list (voiptel-connection-questions.md Q4).
CARRIER_IPS="${DOGRAH_CARRIER_IPS:-84.39.233.90/32}"
# Media arrives from a second host: the first live call's SDP carried
# c=IN IP4 84.39.233.91. Without it, RTP only gets in via conntrack after we
# send first, so the carrier's early media is dropped.
CARRIER_MEDIA_IPS="${DOGRAH_CARRIER_MEDIA_IPS:-84.39.233.90/32,84.39.233.91/32}"

RTP_PORTS="${DOGRAH_RTP_PORTS:-10000-10120}"
TURN_RELAY_PORTS="${DOGRAH_TURN_RELAY_PORTS:-49152-49200}"

# --- Plumbing ----------------------------------------------------------------
APPLY=0
ONLY=""
case "${1:-}" in
  apply) APPLY=1; ONLY="${2:-}" ;;
  ""|plan|--help|-h) ONLY="${2:-}" ;;
  *) echo "usage: $0 [apply] [step]" >&2; exit 2 ;;
esac

C_OK=$'\033[0;32m'; C_SKIP=$'\033[0;34m'; C_WARN=$'\033[1;33m'; C_OFF=$'\033[0m'
# In plan mode the "would run" line already says what happens, so ok() stays
# quiet there rather than claiming a resource was created.
ok()   { [[ $APPLY -eq 1 ]] && echo "${C_OK}  created${C_OFF} $*"; return 0; }
skip() { echo "${C_SKIP}  exists ${C_OFF} $*"; }
warn() { echo "${C_WARN}  warn   ${C_OFF} $*"; }
step() { echo; echo "=== $1 ==="; }

# Run a gcloud mutation, or print it in plan mode.
run() {
  if [[ $APPLY -eq 1 ]]; then
    "$@"
  else
    echo "  would run: $*"
  fi
}

want() { [[ -z "$ONLY" || "$ONLY" == "$1" ]]; }

# Retry a mutation a few times. A service account created a moment ago can
# still be invisible to IAM policy calls (PERMISSION_DENIED "... or it may not
# exist") while it propagates.
retry() {
  local attempt
  for attempt in 1 2 3 4 5 6; do
    "$@" && return 0
    [[ $attempt -lt 6 ]] && { warn "retrying in 10s (IAM propagation)"; sleep 10; }
  done
  return 1
}

# Does a resource exist? Swallows the "not found" stderr that gcloud emits.
exists() { "$@" >/dev/null 2>&1; }

if [[ $APPLY -eq 0 ]]; then
  echo "${C_WARN}PLAN MODE — nothing will be created. Re-run with 'apply' to execute.${C_OFF}"
fi
echo "project=$PROJECT_ID region=$REGION zone=$ZONE"

# --- project -----------------------------------------------------------------
if want project; then
  step "project"
  if exists gcloud projects describe "$PROJECT_ID"; then
    skip "project $PROJECT_ID"
  else
    run gcloud projects create "$PROJECT_ID" --name="Dograh EU"
    ok "project $PROJECT_ID"
  fi
  if gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
    skip "billing linked"
  else
    run gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
    ok "billing linked to $BILLING_ACCOUNT"
  fi
fi

# NOTE: deliberately no `gcloud config set project` — every command below passes
# --project explicitly, so this script never mutates your local gcloud config
# (which currently points at an unrelated project).

# --- apis --------------------------------------------------------------------
if want apis; then
  step "apis"
  APIS=(
    compute.googleapis.com
    storage.googleapis.com
    artifactregistry.googleapis.com
    cloudbuild.googleapis.com
    secretmanager.googleapis.com
    iap.googleapis.com
    iamcredentials.googleapis.com      # GitHub OIDC -> service account tokens (ci step)
    sts.googleapis.com                 # Workload Identity Federation token exchange
    sqladmin.googleapis.com
    servicenetworking.googleapis.com   # required for Cloud SQL private IP
  )
  ENABLED="$(gcloud services list --enabled --project="$PROJECT_ID" --format='value(config.name)' 2>/dev/null || true)"
  TO_ENABLE=()
  for a in "${APIS[@]}"; do
    if grep -qx "$a" <<<"$ENABLED"; then skip "$a"; else TO_ENABLE+=("$a"); fi
  done
  if (( ${#TO_ENABLE[@]} )); then
    run gcloud services enable "${TO_ENABLE[@]}" --project="$PROJECT_ID"
    ok "${TO_ENABLE[*]}"
  fi
fi

# --- ips ---------------------------------------------------------------------
if want ips; then
  step "static IPs"
  for name in dograh-app-ip dograh-sip-ip; do
    if exists gcloud compute addresses describe "$name" --region="$REGION" --project="$PROJECT_ID"; then
      skip "$name ($(gcloud compute addresses describe "$name" --region="$REGION" --project="$PROJECT_ID" --format='value(address)'))"
    else
      run gcloud compute addresses create "$name" --region="$REGION" --project="$PROJECT_ID"
      ok "$name"
    fi
  done
  warn "the sip VM's IP is what VoIPTel must whitelist — send it to them once assigned"
fi

# --- firewall ----------------------------------------------------------------
# Ingress is default-deny on the VPC, so only what is listed here is reachable.
if want firewall; then
  step "firewall"
  fw() {
    local name="$1"; shift
    if exists gcloud compute firewall-rules describe "$name" --project="$PROJECT_ID"; then
      skip "$name"
    else
      run gcloud compute firewall-rules create "$name" --project="$PROJECT_ID" "$@"
      ok "$name"
    fi
  }

  fw allow-web        --direction=INGRESS --action=ALLOW --rules=tcp:80,tcp:443 \
                      --source-ranges=0.0.0.0/0 --target-tags=dograh-app \
                      --description="HTTPS ingress + ACME http-01"

  fw allow-turn       --direction=INGRESS --action=ALLOW \
                      --rules="udp:3478,tcp:3478,udp:5349,tcp:5349,udp:${TURN_RELAY_PORTS}" \
                      --source-ranges=0.0.0.0/0 --target-tags=dograh-app \
                      --description="coturn STUN/TURN + relay range"

  fw allow-sip        --direction=INGRESS --action=ALLOW --rules=tcp:5071 \
                      --source-ranges="$CARRIER_IPS" --target-tags=dograh-sip \
                      --description="SIP signalling from the carrier only"

  fw allow-rtp        --direction=INGRESS --action=ALLOW --rules="udp:${RTP_PORTS}" \
                      --source-ranges="$CARRIER_MEDIA_IPS" --target-tags=dograh-sip \
                      --description="RTP media from the carrier only"

  # ARI is unauthenticated at the transport layer — app VM only, never public.
  fw allow-ari        --direction=INGRESS --action=ALLOW --rules=tcp:8088 \
                      --source-tags=dograh-app --target-tags=dograh-sip \
                      --description="Asterisk ARI, reachable only from the app VM"

  # Asterisk dials out to the media WebSocket on the app VM.
  fw allow-media-ws   --direction=INGRESS --action=ALLOW --rules=tcp:8000 \
                      --source-tags=dograh-sip --target-tags=dograh-app \
                      --description="Asterisk -> Dograh media WebSocket"

  # IAP-tunnelled SSH only. No public port 22.
  fw allow-ssh-iap    --direction=INGRESS --action=ALLOW --rules=tcp:22 \
                      --source-ranges=35.235.240.0/20 --target-tags=dograh-app,dograh-sip \
                      --description="SSH via IAP tunnel only"
fi

# --- storage -----------------------------------------------------------------
if want storage; then
  step "storage"
  if exists gcloud storage buckets describe "gs://$BUCKET" --project="$PROJECT_ID"; then
    skip "gs://$BUCKET"
  else
    run gcloud storage buckets create "gs://$BUCKET" \
      --project="$PROJECT_ID" --location="$REGION" \
      --uniform-bucket-level-access --public-access-prevention
    ok "gs://$BUCKET"
  fi

  SA_EMAIL="${STORAGE_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
  if exists gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID"; then
    skip "service account $STORAGE_SA"
  else
    run gcloud iam service-accounts create "$STORAGE_SA" \
      --project="$PROJECT_ID" --display-name="Dograh object storage"
    ok "service account $STORAGE_SA"
  fi

  run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin
  ok "objectAdmin on gs://$BUCKET (idempotent)"

  # The HMAC key is what makes the S3-compatible XML API work. It is printed
  # ONCE and never retrievable again — capture it straight into the .env.
  if [[ -n "$(gcloud storage hmac list --project="$PROJECT_ID" --filter="serviceAccountEmail=$SA_EMAIL AND state=ACTIVE" --format='value(accessId)' 2>/dev/null || true)" ]]; then
    skip "HMAC key (an active key already exists)"
  else
    warn "creating an HMAC key — the secret is shown once, save it now"
    run gcloud storage hmac create "$SA_EMAIL" --project="$PROJECT_ID"
  fi
fi

# --- sql ---------------------------------------------------------------------
if want sql; then
  step "cloud sql"
  if exists gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID"; then
    skip "instance $SQL_INSTANCE"
  else
    warn "shared-core tiers ($SQL_TIER) are NOT covered by the Cloud SQL SLA"
    warn "if PostgreSQL 17 rejects $SQL_TIER, fall back to db-custom-1-3840 (~\$53/mo)"
    run gcloud sql instances create "$SQL_INSTANCE" \
      --project="$PROJECT_ID" \
      --database-version="$SQL_VERSION" \
      --tier="$SQL_TIER" \
      --zone="$ZONE" \
      --storage-size=20 --storage-type=SSD --storage-auto-increase \
      --backup --backup-start-time=02:00 \
      --retained-backups-count=7 \
      --enable-point-in-time-recovery \
      --no-assign-ip \
      --network="projects/$PROJECT_ID/global/networks/default"
    ok "instance $SQL_INSTANCE (private IP only)"
  fi
  warn "after creation: create the db + user, then run  CREATE EXTENSION IF NOT EXISTS vector;"
fi

# --- registry ----------------------------------------------------------------
if want registry; then
  step "artifact registry"
  if exists gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" --project="$PROJECT_ID"; then
    skip "repo $AR_REPO"
  else
    run gcloud artifacts repositories create "$AR_REPO" \
      --project="$PROJECT_ID" --location="$REGION" --repository-format=docker \
      --description="Dograh api, ui and agent sidecar images"
    ok "repo $AR_REPO"
  fi
  echo "  REGISTRY=${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
fi

# --- schedule ----------------------------------------------------------------
# Pre-launch only. REMOVE before go-live or the customer's number rings dead
# outside working hours — see README "Before go-live".
if want schedule; then
  step "pre-launch instance schedule"
  if exists gcloud compute resource-policies describe dograh-dev-hours --region="$REGION" --project="$PROJECT_ID"; then
    skip "dograh-dev-hours"
  else
    run gcloud compute resource-policies create instance-schedule dograh-dev-hours \
      --project="$PROJECT_ID" --region="$REGION" \
      --vm-start-schedule='0 8 * * MON-FRI' \
      --vm-stop-schedule='0 19 * * MON-FRI' \
      --timezone='Europe/Dublin'
    ok "dograh-dev-hours (08:00-19:00 Mon-Fri Europe/Dublin)"
  fi
  warn "attach with: gcloud compute instances add-resource-policies <vm> --resource-policies=dograh-dev-hours --zone=$ZONE"
  warn "REMOVE THIS BEFORE GO-LIVE"
fi

# --- ci ----------------------------------------------------------------------
# Keyless GitHub Actions access for release.yml (Cloud Build) and deploy.yml
# (Cloud SQL backup + IAP SSH to the app VM). Only workflow runs on main of
# GITHUB_REPO can impersonate the deployer, pinned by the repo's numeric id so
# a renamed or re-created repo with the same name gets nothing.
if want ci; then
  step "ci (GitHub Actions)"
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  DEPLOY_SA_EMAIL="${DEPLOY_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
  BUILD_SA_EMAIL="${BUILD_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
  GITHUB_REPO_ID="${DOGRAH_GITHUB_REPO_ID:-$(gh api "repos/$GITHUB_REPO" --jq .id 2>/dev/null || true)}"
  [[ -n "$GITHUB_REPO_ID" ]] || { echo "set DOGRAH_GITHUB_REPO_ID (gh api repos/$GITHUB_REPO --jq .id)" >&2; exit 1; }

  # Token exchange for Workload Identity Federation (also in the apis step,
  # repeated here so `apply ci` alone is enough).
  ENABLED="$(gcloud services list --enabled --project="$PROJECT_ID" --format='value(config.name)' 2>/dev/null || true)"
  for api in sts.googleapis.com iamcredentials.googleapis.com; do
    if grep -qx "$api" <<<"$ENABLED"; then
      skip "$api"
    else
      run gcloud services enable "$api" --project="$PROJECT_ID"
      ok "$api"
    fi
  done

  if exists gcloud iam workload-identity-pools describe "$WIF_POOL" --location=global --project="$PROJECT_ID"; then
    skip "workload identity pool $WIF_POOL"
  else
    run gcloud iam workload-identity-pools create "$WIF_POOL" --location=global \
      --project="$PROJECT_ID" --display-name="GitHub Actions"
    ok "workload identity pool $WIF_POOL"
  fi

  if exists gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" \
       --workload-identity-pool="$WIF_POOL" --location=global --project="$PROJECT_ID"; then
    skip "OIDC provider $WIF_PROVIDER"
  else
    run gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
      --workload-identity-pool="$WIF_POOL" --location=global --project="$PROJECT_ID" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" \
      --attribute-condition="assertion.repository_id=='${GITHUB_REPO_ID}' && assertion.ref=='refs/heads/main'"
    ok "OIDC provider $WIF_PROVIDER (repo id $GITHUB_REPO_ID, main only)"
  fi

  if exists gcloud iam service-accounts describe "$DEPLOY_SA_EMAIL" --project="$PROJECT_ID"; then
    skip "service account $DEPLOY_SA"
  else
    run gcloud iam service-accounts create "$DEPLOY_SA" \
      --project="$PROJECT_ID" --display-name="GitHub Actions release + deploy"
    ok "service account $DEPLOY_SA"
  fi

  retry run gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA_EMAIL" \
    --project="$PROJECT_ID" --role=roles/iam.workloadIdentityUser --format=none \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository_id/${GITHUB_REPO_ID}"
  ok "GitHub repo $GITHUB_REPO may impersonate $DEPLOY_SA (idempotent)"

  # Least privilege for backups: create one, follow its operation.
  if exists gcloud iam roles describe lightmoveSqlBackup --project="$PROJECT_ID"; then
    skip "custom role lightmoveSqlBackup"
  else
    run gcloud iam roles create lightmoveSqlBackup --project="$PROJECT_ID" --format=none \
      --title="LightMove pre-deploy SQL backup" \
      --permissions=cloudsql.backupRuns.create,cloudsql.backupRuns.get,cloudsql.backupRuns.list,cloudsql.instances.get
    ok "custom role lightmoveSqlBackup"
  fi

  # Project-level roles:
  #   cloudbuild.builds.editor        submit + poll the release build
  #   serviceusage.serviceUsageConsumer  required by `gcloud builds submit`
  #   compute.viewer                  check both VMs are RUNNING
  #   iap.tunnelResourceAccessor      SSH through the IAP tunnel
  for role in roles/cloudbuild.builds.editor roles/serviceusage.serviceUsageConsumer \
              roles/compute.viewer roles/iap.tunnelResourceAccessor \
              "projects/${PROJECT_ID}/roles/lightmoveSqlBackup"; do
    retry run gcloud projects add-iam-policy-binding "$PROJECT_ID" --condition=None --quiet \
      --member="serviceAccount:$DEPLOY_SA_EMAIL" --role="$role" --format=none
    ok "$role"
  done

  # Source uploads for `gcloud builds submit` (bucket-scoped). release.yml
  # passes --gcs-source-staging-dir, so no project-wide bucket listing is needed.
  run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}_cloudbuild" \
    --member="serviceAccount:$DEPLOY_SA_EMAIL" --role=roles/storage.admin --format=none
  ok "storage.admin on gs://${PROJECT_ID}_cloudbuild"

  # The identity release builds run as (cloudbuild.yaml `serviceAccount`).
  # Not the project default, the Compute Engine account, which holds Editor:
  # actAs on that would make the deployer an Editor in all but name.
  if exists gcloud iam service-accounts describe "$BUILD_SA_EMAIL" --project="$PROJECT_ID"; then
    skip "service account $BUILD_SA"
  else
    run gcloud iam service-accounts create "$BUILD_SA" \
      --project="$PROJECT_ID" --display-name="Cloud Build: release images"
    ok "service account $BUILD_SA"
  fi
  retry run gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
    --location="$REGION" --project="$PROJECT_ID" \
    --member="serviceAccount:$BUILD_SA_EMAIL" --role=roles/artifactregistry.writer --format=none
  ok "$BUILD_SA: artifactregistry.writer on $AR_REPO"
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" --condition=None --quiet \
    --member="serviceAccount:$BUILD_SA_EMAIL" --role=roles/logging.logWriter --format=none
  ok "$BUILD_SA: logging.logWriter"
  run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}_cloudbuild" \
    --member="serviceAccount:$BUILD_SA_EMAIL" --role=roles/storage.objectViewer --format=none
  ok "$BUILD_SA: objectViewer on gs://${PROJECT_ID}_cloudbuild (source)"
  retry run gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA_EMAIL" --project="$PROJECT_ID" \
    --member="serviceAccount:$DEPLOY_SA_EMAIL" --role=roles/iam.serviceAccountUser --format=none
  ok "$DEPLOY_SA may run builds as $BUILD_SA"

  # Check release images exist (repo-scoped).
  run gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
    --location="$REGION" --project="$PROJECT_ID" \
    --member="serviceAccount:$DEPLOY_SA_EMAIL" --role=roles/artifactregistry.reader --format=none
  ok "artifactregistry.reader on $AR_REPO"

  # OS Login as root on the app VM only, plus actAs on the VM's service
  # account (required to SSH into a VM that runs as a service account).
  run gcloud compute instances add-iam-policy-binding "$APP_VM" --zone="$ZONE" --project="$PROJECT_ID" \
    --member="serviceAccount:$DEPLOY_SA_EMAIL" --role=roles/compute.osAdminLogin --format=none
  ok "compute.osAdminLogin on $APP_VM"
  VM_SA="$(gcloud compute instances describe "$APP_VM" --zone="$ZONE" --project="$PROJECT_ID" --format='value(serviceAccounts[0].email)')"
  if [[ -n "$VM_SA" ]]; then
    run gcloud iam service-accounts add-iam-policy-binding "$VM_SA" --project="$PROJECT_ID" \
      --member="serviceAccount:$DEPLOY_SA_EMAIL" --role=roles/iam.serviceAccountUser --format=none
    ok "serviceAccountUser on $VM_SA"
  fi

  # OS Login replaces metadata SSH keys on this VM: your own `gcloud compute
  # ssh` keeps working (as an OS Login user, e.g. you_example_com).
  if [[ "$(gcloud compute instances describe "$APP_VM" --zone="$ZONE" --project="$PROJECT_ID" \
          --format='value(metadata.items.enable-oslogin)')" == "TRUE" ]]; then
    skip "OS Login on $APP_VM"
  else
    run gcloud compute instances add-metadata "$APP_VM" --zone="$ZONE" --project="$PROJECT_ID" \
      --metadata=enable-oslogin=TRUE
    ok "OS Login on $APP_VM"
  fi

  echo "  GitHub repo variables (Settings → Secrets and variables → Actions → Variables):"
  echo "    GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}"
  echo "    GCP_DEPLOY_SA=${DEPLOY_SA_EMAIL}"
fi

echo
if [[ $APPLY -eq 0 ]]; then
  echo "${C_WARN}Plan complete. Nothing was created. Re-run: $0 apply${C_OFF}"
else
  echo "${C_OK}Bootstrap complete.${C_OFF} Next: deploy/gcp/README.md — 'Build images'"
fi
