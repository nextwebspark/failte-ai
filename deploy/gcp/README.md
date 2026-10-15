# LightMove.ai on GCP (europe-west1)

Two VMs in `europe-west1-b`, Cloud SQL for Postgres, GCS for call recordings.
Runs the standard Compose stack via the repo's own `setup_remote.sh` installer,
with a thin overlay for what differs on GCP.

```
[ app VM ] e2-standard-2          [ sip VM ] e2-small
 static IP A                       static IP B  <- VoIPTel whitelists this
 nginx / api / ui / redis          asterisk 22
 coturn                             SIP  tcp 5060      (carrier IPs only)
 fallcha-tools                      RTP  udp 10000-10120 (carrier IPs only)
                                    ARI  tcp 8088      (app VM only)
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
| `docker-compose.override.yaml` | App-VM overlay — drops the Postgres container, points `fallcha-tools` at Cloud SQL (the retired sidecars stay commented out for rollback) |
| `configure-env.sh` | Writes `.env` (and `secrets/tools.env`) from Secret Manager |
| `cloudbuild.yaml` | Builds `dograh-api`, `dograh-ui` and `fallcha-tools` for linux/amd64 |
| `verify_gcs.py` | Proves GCS works through the S3 API **before** anything depends on it |
| `secrets/` | Per-service env files. Gitignored — never commit |

The sip VM overlay lives with its stack, at
`deploy/asterisk-voiptel/docker-compose.gcp.yaml`.

## Prerequisites

The agent tools (calendar booking, order lookup, product search) are served by
the in-repo `fallcha-tools` service (`tools/`), so nothing outside this repo has
to be built. The old `calendar-shim` / `product-service` sidecars from
`~/dev/voiptel-agent` and `~/dev/chmarine-agent` are needed only during the
cutover and for rollback (see [Tools service cutover](#tools-service-cutover)).

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
emulation. `deploy/gcp/cloudbuild.yaml` builds `dograh-api`, `dograh-ui` and
`fallcha-tools`; build `asterisk-voiptel` for the sip VM separately.

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

## 5. Tools service (`fallcha-tools`)

`fallcha-tools` (`tools/`, see `tools/README.md`) hosts the agents' third-party
tools: Google Calendar, Google Sheets and the website product catalogue. It
replaces the `calendar-shim` and `chmarine-product-service` sidecars. It sits on
`app-network` with no host ports: the api reaches it at
`http://fallcha-tools:8000`, and nginx forwards only
`/oauth/<provider>/callback` to it. It shares the Cloud SQL database (its own
`fallcha_tools` schema, migrated on container start).

### Secrets

All three are **required**: the overlay runs `fallcha-tools`, and
`configure-env.sh` stops with an error if `dograh-tools-internal-secret` or
`dograh-tools-encryption-keys` is missing. Create them once (values are never
printed back):

```bash
P=dograh-eu
fernet() { python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"; }
fernet | gcloud secrets create dograh-credentials-encryption-keys --data-file=- --project=$P
fernet | gcloud secrets create dograh-tools-encryption-keys --data-file=- --project=$P
openssl rand -hex 32 | gcloud secrets create dograh-tools-internal-secret --data-file=- --project=$P
```

`configure-env.sh` then writes `CREDENTIALS_ENCRYPTION_KEYS` and
`TOOLS_INTERNAL_SECRET` into `.env` (the api and the tools service share the
secret) and the tools-only keys into `deploy/gcp/secrets/tools.env` (see
`secrets/tools.env.example`). `TOOLS_PUBLIC_BASE_URL` defaults to
`PUBLIC_BASE_URL` and `TOOLS_UI_RETURN_URL` to `PUBLIC_BASE_URL/integrations`;
override with `DOGRAH_TOOLS_PUBLIC_BASE_URL` / `DOGRAH_TOOLS_UI_RETURN_URL`.

**Encrypting existing credentials.** The api's migration seals plaintext rows
only when it first runs with the key set. Once the key is set on an install
whose database already passed that migration, run the re-encryption once.
GCP's Cloud SQL is such an install. The script is idempotent and safe to repeat:

```bash
docker compose up -d api        # restart with CREDENTIALS_ENCRYPTION_KEYS
docker compose exec api python -m scripts.reencrypt_credentials --dry-run
docker compose exec api python -m scripts.reencrypt_credentials
```

Never drop a key while rows encrypted with it exist. Rotation is in
`docs/developer/environment-variables.mdx`.

The nginx config is rendered by `dograh-init` from
`deploy/templates/nginx.remote.conf.template`, so pulling this repo and
recreating `dograh-init` + `nginx` picks up the callback route.

### Tools service cutover

GCP is stopped as of 2026-10; this is the plan for when it comes back. Do it in
this order, so no step leaves an agent without a working tool. The old
sidecars keep running until step 7.

1. **Deploy.** Build with `cloudbuild.yaml`, create the secrets, run
   `configure-env.sh`, then bring the stack up with the overlay. For the
   cutover window, uncomment the two sidecar blocks in the overlay so the
   old tools keep answering.
   The VM's copy of the overlay may carry local additions. Merge this file
   into it rather than overwriting it. The api patch mounts described in
   `app-doc/gcp-voice-stack-runbook.md` are the exception: drop them, since
   they would shadow files of the new api image this cutover needs. First
   confirm their changes are in the image.
   `docker compose ps fallcha-tools` must be healthy, and the Integrations
   page must list Google Calendar, Google Sheets and Website product
   catalogue.
2. **Voiptel: Google Calendar.** Integrations → Google Calendar → Connect →
   *Service account key*. Upload the key that is in Secret Manager today
   (`/etc/dograh/sa.json`). In the settings that follow, set:
   - `calendar_id`: the shim's `CALENDAR_ID`;
   - `timezone`: `Europe/Dublin`;
   - `event_summary_prefix`: `Voiptel call`.

   Test the connection.
3. **Voiptel: Google Sheets (orders).** Integrations → Google Sheets →
   Connect → *Use the same service account*. Set:
   - `spreadsheet_id`: the shim's `ORDERS_SHEET_ID`;
   - `orders_tab`: `Orders`.

   Share the spreadsheet with the service account (Viewer is enough for
   lookups). The order header mapping (`order_columns`) defaults to the
   shim's headers. Only if the sheet's headers differ, set it through the API
   (the UI form does not edit nested settings):

   ```bash
   curl -X PATCH https://<host>/api/v1/integrations/connections/<id> \
     -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
     -d '{"config": {"order_columns": {"order_id": "Order ID", "status": "Status"}}}'
   ```

4. **CH Marine: Website product catalogue.** Integrations → Website product
   catalogue → Connect. Set `site_url` to `https://www.chmarine.com`. The
   first sync starts by itself, takes tens of minutes (paced crawling; 2000
   products at most by default) and must finish with a product count.
   - If the count is far off, set `sitemap_url` / `include_paths` and press
     **Sync now**.
   - The old `catalogue.sqlite` is not imported; the catalogue is re-crawled
     into Cloud SQL.
5. **Re-point the agents.** Each connection created an MCP tool ("Google
   Calendar", "Google Sheets", "Website product catalogue"), authenticated by
   a managed bearer credential "<Provider> integration (...)". For each agent,
   pick one of the two options below.
   - **MCP (preferred).** In the node's tool selector → *MCP*, tick the
     functions:
     - Calendar: `check_appointment_availability`, `book_appointment`,
       `cancel_appointment`;
     - Sheets: `look_up_order`;
     - Catalogue: `search_products`, `product_detail`.

     Then untick the old `http_api` tools. The LLM sees the functions as
     `mcp__<tool>__<function>`, so update any prompt text that names the old
     tools.
   - **Keep the `http_api` tools.** Edit each one:
     - Set the URL to the compatibility route, `http://fallcha-tools:8000`
       plus the route below.
       - Calendar: `/v1/google-calendar/availability`, `/book`, `/cancel`.
       - Orders: `/v1/google-sheets/order_lookup`.
       - Catalogue: `/v1/website-catalogue/product_search`,
         `/product_detail`.
     - Replace the old `X-API-Key` credential with the integration's managed
       credential (it sends `Authorization: Bearer <key>`).
     - Each key works only on its own provider's routes.
     - Bodies and responses are unchanged.

     Removing the integration later deletes that credential but does not
     archive these `http_api` tools.

   Do **not** re-run `voiptel-agent/scripts/setup_calendar_tools.py` or
   `chmarine-agent/scripts/setup_tools.py` afterwards. They re-point the tools
   at the sidecars.
6. **Call transfer.** The CH Marine `transfer_to_team` tool resolves its
   destination dynamically from
   `http://chmarine-product-service:8080/transfer_destination`. That endpoint
   is the `TRANSFER_DESTINATION` from `product-service.env` and is **not**
   ported to fallcha-tools. Before stopping the product service, edit the
   tool:
   - set *Destination source* to **Static**;
   - set *Destination* to the current `TRANSFER_DESTINATION` value. It must
     stay trunk-qualified, for example `PJSIP/200@voiptel`; a bare name fails
     with "Allocation failed".

   Changing the destination later is a tool edit, not an env change.

   Then place a test call on a CH Marine workflow and ask for a person. It
   must ring the destination while `chmarine-product-service` is still
   running. Only then go on to step 7. A failed transfer here shows up as
   "Allocation failed" in the api log.
7. **Verify, then retire.** Place a test call per agent:
   - Voiptel: availability → book (the event appears with the "Voiptel call"
     prefix) → cancel. Also run an order lookup.
   - CH Marine: product search → detail → transfer.

   Then comment the sidecar blocks out again and run
   `docker compose up -d --remove-orphans`. Events booked by the old shim
   carry no marker, so the agent cannot cancel them; cancel those in Google
   Calendar.

**Rollback:** uncomment the sidecars, `docker compose up -d calendar-shim
chmarine-product-service`, and re-point the tools (re-running the two setup
scripts does this). Restore the transfer tool's dynamic resolver. Keep
`/var/lib/dograh/chmarine` and the shim env files until the cutover has been
stable for a while.

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

`DOGRAH_WS_URI` must carry **no query string** — LightMove.ai appends per-call
parameters itself.

Then configure the telephony row in the LightMove.ai UI: ARI provider at
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

DOGRAH_SQL_IP=<ip> DOGRAH_EMAIL_FROM='LightMove.ai <no-reply@mail.<domain>>' \
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
- [ ] Daily PD snapshot schedule — this is what protects the Redis AOF, which
      Cloud SQL backups do not cover. (The product catalogue now lives in Cloud
      SQL, schema `fallcha_tools`.)
- [ ] Back up `dograh-credentials-encryption-keys` and
      `dograh-tools-encryption-keys` alongside the database backups: a restored
      database is unreadable without them.
- [ ] Verify externally with `nmap` that Postgres/Redis/MinIO are unreachable.
      Docker's published ports bypass host firewalls like `ufw`, so check from
      outside rather than trusting the host config.
