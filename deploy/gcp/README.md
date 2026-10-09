# Dograh on GCP (europe-west1)

Two VMs in `europe-west1-b`, Cloud SQL for Postgres, GCS for call recordings.
Runs the standard Compose stack via the repo's own `setup_remote.sh` installer,
with a thin overlay for what differs on GCP.

```
[ app VM ] e2-standard-2          [ sip VM ] e2-small
 static IP A                       static IP B  <- VoIPTel whitelists this
 nginx / api / ui / redis          asterisk 22
 coturn                             SIP  tcp 5060      (carrier IPs only)
 calendar-shim                      RTP  udp 10000-10120 (carrier IPs only)
 chmarine-product-service           ARI  tcp 8088      (app VM only)
   |
   +-- Cloud SQL PostgreSQL 17 + pgvector (private IP)
   +-- gs://dograh-voice-audio-eu (S3-compatible XML API)
```

Cost: **~$113/mo** list, **~$90** with sustained-use discount, **~$29** while the
pre-launch schedule is active. Full breakdown in the plan document.

## Files here

| File | Purpose |
|---|---|
| `bootstrap.sh` | Idempotent `gcloud` setup: project, APIs, IPs, firewall, bucket, Cloud SQL, registry |
| `docker-compose.override.yaml` | App-VM overlay — drops the Postgres container, adds the two sidecars |
| `verify_gcs.py` | Proves GCS works through the S3 API **before** anything depends on it |
| `secrets/` | Per-service env files. Gitignored — never commit |

The sip VM overlay lives with its stack, at
`deploy/asterisk-voiptel/docker-compose.gcp.yaml`.

## Prerequisites

**The two agent sidecars are not in version control.** `~/dev/chmarine-agent` and
`~/dev/voiptel-agent` are untracked folders that exist only on one laptop. Cloud
Build has nothing to build from until they are in a repo, so this is a hard
blocker, not a nicety. Commit both (with `.env` gitignored) and push before
starting.

## 1. Bootstrap the project

```bash
./deploy/gcp/bootstrap.sh          # plan — prints what it would do, changes nothing
./deploy/gcp/bootstrap.sh apply    # BILLABLE
```

Every step checks before it creates, so re-running converges drift safely. Run a
single step with `./bootstrap.sh apply firewall`.

Capture the **HMAC key secret** when it prints — it is shown once and is not
retrievable afterwards.

Then create the database, its user, and the extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Confirm `db-g1-small` is actually offerable on PostgreSQL 17 at creation time. If
it is not, fall back to `db-custom-1-3840` (~$53/mo instead of ~$29).

## 2. Verify GCS before trusting it

```bash
pip install aioboto3
export S3_BUCKET=dograh-voice-audio-eu S3_REGION=europe-west1 \
       S3_ENDPOINT_URL=https://storage.googleapis.com \
       S3_SIGNATURE_VERSION=s3v4 S3_ADDRESSING_STYLE=virtual \
       AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
python deploy/gcp/verify_gcs.py
```

This exercises the exact calls `api/services/filesystem/s3.py` makes, including
both presigned-URL flows. If signature errors appear, try
`S3_ADDRESSING_STYLE=path`.

If presigning is fundamentally broken, **do not simply fall back to the MinIO
backend** — `api/services/filesystem/minio.py` applies an anonymous bucket policy
granting `PutObject`/`DeleteObject` to `*` and returns unsigned URLs, and nginx
proxies `/voice-audio/` publicly.

## 3. Build images

`pipecat/` is a submodule and part of the API build context:

```bash
git submodule update --init --recursive
```

Build for **linux/amd64** in Cloud Build — the dev machine is arm64 and the API
image (pipecat with ~18 extras plus a static ffmpeg) is far too slow under
emulation. Build four images: `dograh-api`, `dograh-ui`, `calendar-shim`,
`product-service`, plus `asterisk-voiptel` for the sip VM.

## 4. App VM

`e2-standard-2`, Ubuntu 22.04, 30 GB pd-balanced, static IP A, tag `dograh-app`.

Set `{"userland-proxy": false}` in `/etc/docker/daemon.json` **before** first
start, or coturn's relay range spawns one `docker-proxy` process per published
port.

```bash
git clone <fork> dograh && cd dograh
git submodule update --init --recursive
sudo ./setup_remote.sh     # installs Docker, nginx, Let's Encrypt, coturn
```

`setup_remote.sh` issues a real Let's Encrypt cert against `<ip>.sslip.io` with no
domain required — ideal for first bring-up. Move to a real domain later with
`scripts/setup_custom_domain.sh`.

Then bring the stack up **with the overlay**:

```bash
export COMPOSE_FILE=docker-compose.yaml:deploy/gcp/docker-compose.override.yaml
docker compose --profile remote up -d
```

Exporting `COMPOSE_FILE` in the shell profile means you cannot later forget the
overlay and silently start a second Postgres container.

### `.env` notes

`DATABASE_URL` is **hardcoded in the root `docker-compose.yaml`**, so setting it in
`.env` alone does nothing — the overlay is what redirects it at Cloud SQL. It still
needs to be present in `.env` for the overlay to interpolate.

```
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://dograh:<pw>@<cloudsql-private-ip>:5432/dograh
REGISTRY=europe-west1-docker.pkg.dev/<project>/dograh
FASTAPI_WORKERS=2
ENABLE_SIGNUP=false
ENABLE_AWS_S3=true
S3_BUCKET=dograh-voice-audio-eu
S3_REGION=europe-west1
S3_ENDPOINT_URL=https://storage.googleapis.com
S3_SIGNATURE_VERSION=s3v4
S3_ADDRESSING_STYLE=virtual
AWS_ACCESS_KEY_ID=<HMAC access id>
AWS_SECRET_ACCESS_KEY=<HMAC secret>
OSS_JWT_SECRET=<openssl rand -hex 32>
TURN_SECRET=<openssl rand -hex 32>
DOGRAH_DEVOPS_SECRET=<openssl rand -hex 32>
TELEPHONY_WS_TOKEN_SECRET=<openssl rand -hex 32>
```

Three things that will bite otherwise:

- **`OSS_JWT_SECRET` defaults to `change-me-in-production`** (`api/constants.py:258`).
- **Langfuse is all-or-nothing.** `api/constants.py:24-31` raises at *import* if the
  host and keys are set but `LANGFUSE_PROJECT_ID` is not, taking down the API and
  the ARQ worker together. Leave the whole block unset unless all four are present.
- **The PostHog key is hardcoded** in `docker-compose.yaml` and points at the
  upstream Dograh project. Set `ENABLE_TELEMETRY=false` or supply your own.

Store the finished `.env` in Secret Manager — it is the only copy of these secrets.

### Why MinIO is still running

The overlay keeps the MinIO container even though storage is GCS. Two reasons:

1. `deploy/templates/nginx.remote.conf.template` hardcodes
   `proxy_pass http://minio:9000/voice-audio/`, and nginx refuses to start if that
   name does not resolve.
2. It is the rollback path during the storage migration, since
   `storage_backend` is a per-row enum and historical rows still say `minio`.

It is inert once `ENABLE_AWS_S3=true` — `MinioFileSystem` is only constructed for
rows whose backend is `minio`, so the anonymous bucket policy is never applied.
Remove it **together with** the nginx `/voice-audio/` location, never separately.

## 5. Sidecar configuration

Both are reached over the Docker network with no published ports:
`http://calendar-shim:8080` and `http://chmarine-product-service:8080`.

**The tool URLs live in the database** and currently say `http://localhost:8090` /
`:8091`. Re-point them with `voiptel-agent/scripts/setup_calendar_tools.py` and
`chmarine-agent/scripts/setup_tools.py`, or every tool call fails at runtime while
the agent still sounds healthy.

Copy `catalogue.sqlite` to `/var/lib/dograh/chmarine` rather than re-crawling —
a rebuild costs an hour of deliberately slow crawling. Refresh later with:

```bash
docker compose run --rm chmarine-product-service python ingest.py --limit 400
```

## 6. SIP VM

`e2-small`, Ubuntu 22.04, 20 GB, static IP B, tag `dograh-sip`.

```bash
cd deploy/asterisk-voiptel
docker compose -f docker-compose.yaml -f docker-compose.gcp.yaml up -d
```

`.env` additions beyond the base variables:

```
PUBLIC_IP=<static IP B>        # external_media_address / external_signaling_address
SIP_INTERNAL_IP=<sip VM internal IP>
APP_INTERNAL_IP=<app VM internal IP>
ASTERISK_IMAGE=europe-west1-docker.pkg.dev/<project>/dograh/asterisk-voiptel:22
DOGRAH_WS_URI=ws://<app VM internal IP>:8000/api/v1/telephony/ws/ari
RTP_START=10000
RTP_END=10120
INBOUND_MODE=echo             # switch to `stasis` once echo works
```

`DOGRAH_WS_URI` must carry **no query string** — Dograh appends per-call
parameters itself.

Then configure the telephony row in the Dograh UI: ARI provider at
`http://<sip-internal-ip>:8088`, Stasis app name exactly matching both the
`ari.conf` user section and the `websocket_client.conf` section name.

**Blocked on VoIPTel** for the SIP password, the registrar address discrepancy, and
the full carrier source-IP list. Everything else ships without it.

## Billing (Stripe) and email (Resend)

Both are optional. `configure-env.sh` turns each on only when its secret exists:

```bash
printf 'sk_test_...' | gcloud secrets create dograh-stripe-secret-key --data-file=- --project=dograh-eu
printf 'whsec_...'   | gcloud secrets create dograh-stripe-webhook-secret --data-file=- --project=dograh-eu
printf 're_...'      | gcloud secrets create dograh-resend-api-key --data-file=- --project=dograh-eu

DOGRAH_SQL_IP=<ip> DOGRAH_EMAIL_FROM='Failte AI <no-reply@mail.<domain>>' \
  ./deploy/gcp/configure-env.sh
docker compose up -d api
```

- **Stripe webhook:** add a dashboard endpoint at
  `https://<PUBLIC_BASE_URL>/api/v1/billing/stripe/webhook` with the five events
  listed in `docs/deployment/stripe-billing.mdx`. Its `whsec_` differs from the one
  `stripe listen` prints locally; store the dashboard one.
- **Resend:** the sending domain must be verified (SPF + DKIM records) before
  real users get mail. `onboarding@resend.dev` only reaches the Resend account
  owner.
- `UI_APP_URL` defaults to `PUBLIC_BASE_URL`, which is where emailed links and
  Stripe's return URLs land. For Google sign-in, add
  `<PUBLIC_BASE_URL>/auth/google/callback` to the OAuth client's redirect URIs.

## Before go-live

- [ ] **Remove the pre-launch instance schedule** — do this *first*, before adding
      the uptime check, or it pages every evening at 19:00:
      ```bash
      gcloud compute instances remove-resource-policies dograh-app \
        --resource-policies=dograh-dev-hours --zone=europe-west1-b
      ```
      Leaving it on means the customer's number rings dead outside working hours.
- [ ] Stop stopping the Cloud SQL instance.
- [ ] Uptime check on `/api/v1/health` + alert policy.
- [ ] Ops Agent on both VMs (memory and disk are not collected by default).
- [ ] Daily PD snapshot schedule — this is what protects the SQLite catalogue and
      the Redis AOF, neither of which Cloud SQL backups cover.
- [ ] Verify externally with `nmap` that Postgres/Redis/MinIO are unreachable.
      Docker's published ports bypass host firewalls like `ufw`, so check from
      outside rather than trusting the host config.
