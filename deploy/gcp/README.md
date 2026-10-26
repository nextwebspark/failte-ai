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
| `bootstrap.sh` | Idempotent `gcloud` setup: project, APIs, log retention (`logging`), IPs, firewall, bucket, Cloud SQL, registry, GitHub Actions identity (`ci`) |
| `docker-compose.override.yaml` | App-VM overlay — drops the Postgres container, points `fallcha-tools` at Cloud SQL, pins api/ui/fallcha-tools to `LIGHTMOVE_VERSION` (the retired sidecars stay commented out for rollback) |
| `configure-env.sh` | Writes `.env` (and `secrets/tools.env`) from Secret Manager |
| `cloudbuild.yaml` | Builds the release images `dograh-api`, `dograh-ui` and `fallcha-tools` for linux/amd64, tagged `X.Y.Z` |
| `deploy.sh` | Runs on the app VM: switches the stack to one release, health-checks it, rolls back on failure |
| `remote-deploy.sh` | Piped over SSH by the Deploy workflow: runs that release's `deploy.sh` as a systemd unit and streams its log |
| `certbot-deploy-hook.sh` | certbot renewal hook: copies the renewed certificate into the install's `certs/` and restarts nginx |
| `verify_gcs.py` | Proves GCS works through the S3 API **before** anything depends on it |
| `secrets/` | Per-service env files. Gitignored — never commit |

The sip VM overlay lives with its stack, at
`deploy/asterisk-voiptel/docker-compose.gcp.yaml`.

## Releases and deploys

Production changes only through two GitHub Actions workflows. Nothing is built
or copied to the VM by hand.

| Workflow | Run it when | What it does |
|---|---|---|
| **Release** (`release.yml`) | main has what you want to ship | Full CI on main's head → next version → Cloud Build images tagged `X.Y.Z` → tag `vX.Y.Z` + GitHub Release with notes |
| **Deploy** (`deploy.yml`) | you approve a release for production | Checks images and both VMs → Cloud SQL backup (prunes pre-deploy backups older than 30 days) → IAP SSH → that release's `deploy.sh` (re-syncs `.env` from Secret Manager, swaps the images) → public health check |

**Versions.** Semver tags `vX.Y.Z`, starting at `v0.1.0`. When you run
Release you pick the bump: `patch` (fixes), `minor` (features), `major`
(breaking). Tags are the only record of versions: nothing is committed back to
main, and `api/pyproject.toml` / `ui/package.json` keep upstream's numbers.
The api reports the release in `/api/v1/health` → `version`.

**Ship a release**

1. Merge to main only when the PR's `ci-ok` check is green.
2. Actions → **Release** → Run workflow (branch `main`) → choose the bump.
   About 55 minutes, mostly the API image build.
3. Actions → **Deploy** → Run workflow → version (empty = latest release).
   This click is the production approval.

**Roll back.** Run Deploy with the older version. It swaps the images back;
it does **not** reverse database migrations (the api runs `alembic upgrade
head` on start), so keep migrations backward compatible, or roll forward with
a fix release. `deploy.sh` also rolls back by itself when the new version
fails its health check (from the second deploy on; the first has nothing to
roll back to, so watch it). A manual roll back keeps the current settings: the
older release re-syncs `.env` from Secret Manager if it already does so (see
below), otherwise it leaves `.env` as it is.

**Where the deploy runs.** Deploy starts `deploy.sh` on the VM as a transient
systemd unit (`deploy/gcp/remote-deploy.sh`) and streams its log into the job.
If the SSH session drops or the job is cancelled, the deploy still finishes or
rolls back on the VM. The job summary names the unit; read it with
`journalctl -u lightmove-deploy-<run>-<attempt>`.

**Settings ship with the release.** Before switching, `deploy.sh` runs that
release's `configure-env.sh`. A secret added to Secret Manager (and granted to
`dograh-app-sa`) goes live with the next Deploy, with no SSH; re-running
Deploy for the current version is enough. Values an operator chooses keep what
`.env` has: `ENABLE_SIGNUP`, `FASTAPI_WORKERS`, `EMAIL_FROM`,
`STRIPE_AUTOMATIC_TAX`, `RETENTION_PURGE_DRY_RUN`, `PLATFORM_MODELS_ENABLED`
and `PLATFORM_VERTEX_PROJECT_ID`. Everything else (secrets, `DATABASE_URL`,
storage, `TELEPHONY_WS_TOKEN_ENFORCE=true`, and the tools URLs and
`CORS_ALLOWED_ORIGINS`, which follow `PUBLIC_BASE_URL`) is rewritten, so a hand
edit or `DOGRAH_*` override of those lasts only until the next Deploy. The
encryption keys are checked before anything is written: a Secret Manager value
that drops a key still in `.env` or `tools.env` stops the deploy (see
[Encryption at rest](#encryption-at-rest) and the fallcha-tools keys comment in
`configure-env.sh`); so does a value that is not a list of Fernet keys. Each run
also leaves a root-only `.env.bak.<UTC timestamp>` next to `.env` (the newest 10
are kept). Copies of `.env` and `tools.env` from before the deploy stay in
`/var/backups/lightmove/pre-deploy/` (`env`, `tools.env`) and are put back if
the deploy stops before the switch or rolls back. A rollback keeps the synced
`CREDENTIALS_ENCRYPTION_KEYS` and `TOOLS_ENCRYPTION_KEYS` (unattended runs only
ever add keys): the new version may already have encrypted rows with an added
key. Because a rollback restores the previous secrets too, rotate a
credential by adding the new value, deploying, and only then revoking the old
one.

**What Deploy refuses to do**

- Start a VM. Both VMs must already be running (the app VM alone parks the
  telephony config), so outside the `dograh-dev-hours` window it fails fast.
- Overwrite hand edits. If tracked files on the VM differ from the repo, the
  deploy stops and lists them. Server changes go through a PR and a release.
- Cut live calls without waiting. It waits up to 10 minutes for active calls
  to finish before recreating the api.

**Merge gate.** `ci.yml` runs on every PR: api tests, tools tests, UI lint +
unit tests + build, and the format/OpenAPI drift check, each only when its
paths changed. `ci-ok` sums them up. On GitHub Free a private repo cannot
enforce it, so Release re-runs the full suite and stops on any failure. On a
paid plan, make it binding once:

```bash
gh api -X POST repos/nextwebspark/failte-ai/rulesets --input - <<'JSON'
{"name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
   {"type": "pull_request", "parameters": {"required_approving_review_count": 0,
     "dismiss_stale_reviews_on_push": false, "require_code_owner_review": false,
     "require_last_push_approval": false, "required_review_thread_resolution": false}},
   {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": true,
     "required_status_checks": [{"context": "ci-ok"}]}}]}
JSON
```

### One-time setup

1. **GCP identity for GitHub:** `./deploy/gcp/bootstrap.sh apply ci` (plan
   first without `apply`). It enables the STS / IAM Credentials APIs and
   creates:
   - the Workload Identity pool (only `main` of this repo, pinned by repo id);
   - `github-deployer`: the identity the workflows act as, with narrow roles;
   - `lightmove-build`: the identity release builds run as, limited to pushing
     to Artifact Registry. It replaces the project's default build account,
     which holds Editor.

   It also turns on OS Login for the app VM and prints two values.
2. **GitHub repo variables** (Settings → Secrets and variables → Actions →
   Variables): `GCP_WIF_PROVIDER` and `GCP_DEPLOY_SA` from step 1, plus
   `PUBLIC_BASE_URL` (e.g. `https://app.lightmove.ai`; Deploy refuses to run
   without it). Optional: `VM_APP_DIR` (default `/opt/lightmove/dograh`).
3. **App VM checkout** (done 2026-10-16). The install is a git checkout at
   `/opt/lightmove/dograh`, owned by root, fetching over a read-only deploy key
   with github.com's host key pinned:

   ```bash
   sudo ssh-keygen -t ed25519 -N '' -f /root/.ssh/lightmove_deploy -C dograh-app-deploy
   # add /root/.ssh/lightmove_deploy.pub as a read-only deploy key on the repo
   # put github.com's ed25519 key (api.github.com/meta) in /root/.ssh/known_hosts_github
   SSHCMD='ssh -i /root/.ssh/lightmove_deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/root/.ssh/known_hosts_github -o StrictHostKeyChecking=yes'
   sudo mkdir -p /opt/lightmove
   sudo env GIT_SSH_COMMAND="$SSHCMD" git clone git@github.com:nextwebspark/failte-ai.git /opt/lightmove/dograh   # no submodules: images are prebuilt
   sudo git -C /opt/lightmove/dograh config core.sshCommand "$SSHCMD"
   echo /certs/ | sudo tee -a /opt/lightmove/dograh/.git/info/exclude
   ```

   Runtime state copied from the old install (`~/dograh/dograh`): `.env`,
   `certs/` (nginx mounts it) and the sidecar env files in
   `deploy/gcp/secrets/`. `.env` additions:

   ```
   COMPOSE_PROJECT_NAME=dograh                     # the old project: same volumes
   COMPOSE_FILE=docker-compose.yaml:deploy/gcp/docker-compose.override.yaml
   COMPOSE_PROFILES=remote,legacy-sidecars         # back to `remote` after the tools cutover
   PUBLIC_HOST=app.lightmove.ai
   PUBLIC_BASE_URL=https://app.lightmove.ai
   ```

   Then `sudo env ENV_FILE=/opt/lightmove/dograh/.env DOGRAH_SQL_IP=10.70.0.3
   ./deploy/gcp/configure-env.sh` (after creating the three secrets, each
   readable by `dograh-app-sa`; it refuses to invent a
   `CREDENTIALS_ENCRYPTION_KEYS` unless `DOGRAH_GENERATE_CREDENTIALS_KEY=1`, see
   "Encryption at rest"). Root's docker already has the Artifact
   Registry credential helper; deploys run as root with `HOME=/root`.
4. **Domain** (done 2026-10-16). `app.lightmove.ai` is a Cloudflare DNS-only A
   record to the app VM. The certificate was issued by webroot against the
   nginx that was running, without restarting anything, and copied into the
   new install:

   ```bash
   sudo certbot certonly --webroot -w <dir nginx serves certs/ from> \
     --non-interactive --agree-tos --register-unsafely-without-email -d app.lightmove.ai
   sudo cp /etc/letsencrypt/live/app.lightmove.ai/fullchain.pem /opt/lightmove/dograh/certs/local.crt
   sudo cp /etc/letsencrypt/live/app.lightmove.ai/privkey.pem   /opt/lightmove/dograh/certs/local.key
   ```

   `/etc/letsencrypt/renewal/app.lightmove.ai.conf` uses
   `/opt/lightmove/dograh/certs` as its webroot. **After the first deploy**,
   install the renewal hook (it replaces the old one pinned to the old path),
   then check renewal works end to end:

   ```bash
   sudo install -m 755 /opt/lightmove/dograh/deploy/gcp/certbot-deploy-hook.sh \
     /etc/letsencrypt/renewal-hooks/deploy/dograh-reload.sh
   sudo certbot renew --cert-name app.lightmove.ai --dry-run
   ```

   `setup_custom_domain.sh` is not used here: it force-recreates the whole
   stack with `:latest` images through `remote_up.sh`.
5. **First deploy:** Release (any bump gives `v0.1.0`), then Deploy `0.1.0`.
   The first switch moves the stack from the old install to this one under
   the same project name, so containers are recreated in place, volumes are
   kept, and the sslip URL stops serving (its certificate is no longer
   mounted). Then follow [Tools service cutover](#tools-service-cutover).

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

**Log retention.** The `logging` step sets the project's `_Default` Cloud Logging
bucket to keep entries for 30 days (`DOGRAH_LOG_RETENTION_DAYS` overrides), and
puts it back if someone changes it in the console. App logs can carry phone
numbers and call metadata, so they are kept no longer than that. Run it alone
with `./deploy/gcp/bootstrap.sh apply logging`; the identity running it needs
`logging.buckets.update` (`roles/logging.configWriter`, or Owner/Editor). Check it:

```bash
gcloud logging buckets describe _Default --location=global --project=dograh-eu \
  --format='value(retentionDays)'
```

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

### Data retention

The app enforces retention itself: a daily ARQ cron at 03:17 UTC
(`api/services/retention/purge.py`) deletes call recordings, transcripts and
call content once a run is older than its organisation's
**Call data retention (days)** setting (default 90, 1–365), clears widget
visitor IP/user agent after 30 days and webhook payloads after 30 days.

Two env vars in the app VM's `.env` control rollout: `RETENTION_PURGE_ENABLED`
(app default `true`; `false` makes the cron log that it is disabled and do
nothing) and `RETENTION_PURGE_DRY_RUN` (app default `false`; `true` deletes
nothing and logs one line per organisation: its id, then the counts of runs,
campaigns, queued rows, widget sessions and webhook deliveries a pass would
purge, counts only). An organisation whose stored retention setting is invalid
is skipped and logged at ERROR.

**Production deletes for real from the first deploy:** `configure-env.sh` sets
`RETENTION_PURGE_DRY_RUN=false`. A dry run is still available, for example to
preview the effect of a shorter retention setting: re-run
`DOGRAH_RETENTION_PURGE_DRY_RUN=true ./deploy/gcp/configure-env.sh`, then
redeploy so the containers pick it up, and read the lines with
`docker compose logs api | grep "Retention purge dry run"`. Later Deploys keep
the dry run; re-run with `DOGRAH_RETENTION_PURGE_DRY_RUN=false` to switch
deletion back on.

Database backups: automated backups 7 days, PITR 7 days, pre-deploy backups
pruned after 30 days (`deploy.yml` deletes its own on-demand backups, the ones
described `pre-deploy v…`, older than 30 days after taking a new one; re-run
`bootstrap.sh apply ci` once so the deploy service account has
`cloudsql.backupRuns.delete`, otherwise the prune only warns). On-demand
backups taken by hand are not pruned: delete them yourself within 30 days.

`bootstrap.sh apply storage` adds a bucket lifecycle rule as a backstop:
objects under `transcripts/` are deleted after 365 days (the maximum setting).
`recordings/` has **no** lifecycle rule on purpose: it also holds agent prompt
audio (`recordings/{org_id}/{recording_id}/{file}`) that agents play on every
call, and a prefix rule cannot tell those apart from call recordings. Call
recordings rely on the app purge. The script sets the bucket's whole lifecycle
config, so add any other rule there rather than in the console. Check it with:

```bash
gcloud storage buckets describe gs://dograh-voice-audio-eu --format='value(lifecycle_config)'
```

## 3. Build images

`pipecat/` is a submodule and part of the API build context:

```bash
git submodule update --init --recursive
```

Build for **linux/amd64** in Cloud Build — the dev machine is arm64 and the API
image (pipecat with ~18 extras plus a static ffmpeg) is far too slow under
emulation. `deploy/gcp/cloudbuild.yaml` builds `dograh-api`, `dograh-ui` and
`fallcha-tools`; the **Release** workflow runs it (see
[Releases and deploys](#releases-and-deploys)). Build `asterisk-voiptel` for
the sip VM separately; it is not part of a release.

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
ENABLE_SIGNUP=true
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
TELEPHONY_WS_TOKEN_ENFORCE=true
CREDENTIALS_ENCRYPTION_KEYS=<Fernet key; see "Encryption at rest">
CORS_ALLOWED_ORIGINS=<PUBLIC_BASE_URL, e.g. https://app.lightmove.ai>
RETENTION_PURGE_DRY_RUN=false
```

`configure-env.sh` writes all of these. Production (`ENVIRONMENT=production`)
refuses to start without `CREDENTIALS_ENCRYPTION_KEYS`, and never answers CORS
with `*`: it uses `CORS_ALLOWED_ORIGINS` (the script defaults it to
`PUBLIC_BASE_URL`; add origins with `DOGRAH_CORS_ALLOWED_ORIGINS=a,b`), or the
origin of `PUBLIC_BASE_URL` when the list is unset. The embed widget on customer
sites is unaffected: `/api/v1/public/embed/*` answers CORS itself, per embed
token's allowed domains. `TELEPHONY_WS_TOKEN_ENFORCE=true` makes the telephony
media WebSocket refuse URLs without a token minted with
`TELEPHONY_WS_TOKEN_SECRET` (Secret Manager `dograh-telephony-ws-token-secret`,
else the `.env` value, else a generated one; rotating it only drops calls in
flight).

Three things that will bite otherwise:

- **`OSS_JWT_SECRET` defaults to `change-me-in-production`** (`api/constants.py:258`).
- **Langfuse is all-or-nothing.** `api/constants.py:24-31` raises at *import* if the
  host and keys are set but `LANGFUSE_PROJECT_ID` is not, taking down the API and
  the ARQ worker together. Leave the whole block unset unless all four are present.
- **PostHog is off unless you supply a key.** `POSTHOG_API_KEY` / `POSTHOG_KEY`
  are empty by default and `ENABLE_TELEMETRY=false` disables both the API and the
  UI clients. If you want analytics, use your own EU project (`eu.i.posthog.com`)
  and list PostHog as a sub-processor.

Store the finished `.env` in Secret Manager — it is the only copy of these secrets.

### Why MinIO is still running

The overlay keeps the MinIO container even though storage is GCS. Two reasons:

1. `deploy/templates/nginx.remote.conf.template` hardcodes
   `proxy_pass http://minio:9000/voice-audio/`, and nginx refuses to start if that
   name does not resolve.
2. It is the rollback path during the storage migration, since
   `storage_backend` is a per-row enum and historical rows still say `minio`.

It takes no new data once `ENABLE_AWS_S3=true` — `MinioFileSystem` is only
constructed for rows whose backend is `minio`. Older versions left an anonymous
read/write/list policy on the `voice-audio` bucket, and nginx still proxies
`/voice-audio/` to it, so the API removes that policy at every startup
(`secure_legacy_minio_bucket` in `api/services/storage.py`; a failure is logged as
a `Bucket setup note` warning). Verify it once after the first deploy:

```bash
# Anonymous listing must be refused: prints 403 (200 means the bucket is still public).
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9000/voice-audio/

# Or ask MinIO directly, if the image ships the mc client. Prints
# "Access permission for `local/voice-audio` is `private`" (older mc: "none").
docker compose exec minio sh -c \
  'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc anonymous get local/voice-audio'
```

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

Create all three once (values are never printed back). The overlay runs
`fallcha-tools`, so `configure-env.sh` stops with an error if
`dograh-tools-internal-secret` or `dograh-tools-encryption-keys` is missing.
Create `dograh-credentials-encryption-keys` here too, so the key lives in
Secret Manager rather than only in `.env`: without it (and with no key in
`.env`) `configure-env.sh` stops unless you pass
`DOGRAH_GENERATE_CREDENTIALS_KEY=1` (see
[Encryption at rest](#encryption-at-rest)):

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
override with `DOGRAH_TOOLS_PUBLIC_BASE_URL` / `DOGRAH_TOOLS_UI_RETURN_URL`
(until the next Deploy, which derives them from `PUBLIC_BASE_URL` again).

**Platform Google client (optional).** When both `dograh-google-oauth-client-id`
and `dograh-google-oauth-client-secret` exist, `tools.env` also gets
`TOOLS_GOOGLE_CLIENT_ID` / `TOOLS_GOOGLE_CLIENT_SECRET`, and every workspace
can connect Google Calendar and Sheets in one click. The client needs the
redirect URIs `<TOOLS_PUBLIC_BASE_URL>/oauth/google-calendar/callback` and
`.../google-sheets/callback`, the Calendar and Sheets APIs enabled in its
project, and the `calendar.events`, `calendar.readonly` and `spreadsheets`
scopes on its consent screen. The same two secrets also turn on Google
sign-in (see "Billing (Stripe), email (Resend) and Google sign-in"): both
features are on with both secrets and off otherwise. After re-running the
script, `sudo docker compose up -d api fallcha-tools` (a plain `restart` does
not re-read `tools.env`). A new secret for the same client applies in place,
and connections the old secret got rejected for retry on that start; a new
client id leaves existing connections on the old client, so keep that client
alive until they reconnect. A replica or rollback started with older settings
writes its secret back, so roll every replica forward together.

Those scopes are *sensitive*: until Google verifies the app (privacy policy and
terms URLs on a verified domain, scope justification, a demo video), the
consent screen warns "Google hasn't verified this app" and at most 100 users
can grant them. Sign-in's `openid email profile` needs no review. Google also
keeps only about 100 live refresh tokens per Google account per client, and
every connect re-consents, so one account connecting very many workspaces
loses its oldest connections (they show as `grant_revoked`).

### Encryption at rest

`CREDENTIALS_ENCRYPTION_KEYS` (comma-separated Fernet keys, the first one
encrypts) seals every stored secret in the database: workspace credentials
(`external_credentials.credential_data`), telephony provider credentials
(`telephony_configurations.credentials`), integration connection details
(`integrations.connection_details`) and organization configuration values
(`organization_configurations.value`, which holds model API keys, Langfuse keys
and legacy telephony settings). Each value is stored as a
`{"_enc": "v1", "ct": "<Fernet token>"}` envelope; the app decrypts on read.

- **Startup.** With `ENVIRONMENT=production` the api and worker refuse to start
  without keys, and every start checks that the keys open an existing envelope,
  so a wrong or dropped key fails the deploy (and its health check) instead of
  breaking calls later.
- **Where the key comes from.** `configure-env.sh` decides before it writes
  anything (and every run first copies `.env` to a root-only
  `.env.bak.<UTC timestamp>`, keeping the newest 10):
  - the Secret Manager secret `dograh-credentials-encryption-keys` and `.env`
    agree, or only one of them has a value: that value (a `.env`-only key gets a
    warning to store it in Secret Manager);
  - both have values and Secret Manager's still holds every key in `.env` (a
    new key added in front for rotation): Secret Manager's, so a Deploy
    rotates;
  - **both have values and Secret Manager's drops a key in `.env`: it stops**
    and changes nothing (a Deploy fails before switching). Re-run
    with `DOGRAH_CREDENTIALS_KEYS_OVERRIDE=sm` to take Secret Manager's value
    (the last rotation step) or `=env` to keep
    `.env`'s (then update the secret to match). Unsure which key encrypted the
    data? Set the secret to both, comma-separated, and use `=sm`: every listed
    key decrypts;
  - **neither has one: it stops**, because on a rebuilt VM the database may
    already hold data encrypted with a key that is only unreadable for now
    (grant access to the secret or restore it from the backup). Only on a
    **first install with an empty database** re-run with
    `DOGRAH_GENERATE_CREDENTIALS_KEY=1`: it generates a key and stores it in
    Secret Manager when it may create secrets, or warns loudly that the key
    exists only in `.env`. In that last case copy it up at once:

  ```bash
  sudo grep '^CREDENTIALS_ENCRYPTION_KEYS=' /opt/lightmove/dograh/.env | cut -d= -f2- \
    | gcloud secrets create dograh-credentials-encryption-keys --data-file=- \
        --replication-policy=user-managed --locations=europe-west1 --project=dograh-eu
  gcloud secrets add-iam-policy-binding dograh-credentials-encryption-keys --project=dograh-eu \
    --member=serviceAccount:dograh-app-sa@dograh-eu.iam.gserviceaccount.com \
    --role=roles/secretmanager.secretAccessor
  ```

- **Existing rows.** Migrations `00cb7a7a62b1` and `17450c2f9b60` (the api runs
  `alembic upgrade head` on start) encrypt existing plaintext telephony,
  integration, organization configuration and user configuration rows in place
  when the key is set; `6b0c8484ba5a` did the same for workspace credentials. Rows written before the key existed, or on a database
  that passed those migrations without a key, are sealed by the re-encryption
  script, which is idempotent and safe to repeat:

  ```bash
  docker compose exec api python -m scripts.reencrypt_credentials --dry-run
  docker compose exec api python -m scripts.reencrypt_credentials
  ```

- **Rotation.** Supported without downtime:
  1. Generate a new key and set the secret to `<new>,<old>` (new first):
     `printf '%s,%s' "$NEW" "$OLD" | gcloud secrets versions add dograh-credentials-encryption-keys --data-file=- --project=dograh-eu`.
  2. Run Deploy (re-running Deploy for the current version is enough): the
     secret still holds `<old>`, so `configure-env.sh` takes it without an
     override and every api and worker restarts holding both keys.
  3. `docker compose exec api python -m scripts.reencrypt_credentials` re-seals
     every row of all five columns under the new key; it exits non-zero and lists
     `table#id` for any row it cannot open.
  4. Set the secret to `<new>` only, re-run `configure-env.sh` with
     `DOGRAH_CREDENTIALS_KEYS_OVERRIDE=sm`, restart.
     Keep the old key with the backups taken before step 3: restoring one of them
     needs it.
- **Never drop a key while rows encrypted with it exist**, and back the key up
  with the database backups: a restored database is unreadable without it.
- **Rolling back past the release that added `00cb7a7a62b1`.** Older images
  cannot read the encrypted telephony, integration and organization
  configuration rows, and `deploy.sh` never reverses migrations. Decrypt first,
  with the keys still set, then deploy the older tag:
  `docker compose exec api alembic -c api/alembic.ini downgrade b7c3e9a41d20`.
  Rolling back only past the release that added `17450c2f9b60` (user
  configurations) decrypts just that table:
  `docker compose exec api alembic -c api/alembic.ini downgrade 00cb7a7a62b1`.

The nginx config is rendered by `dograh-init` from
`deploy/templates/nginx.remote.conf.template`, so pulling this repo and
recreating `dograh-init` + `nginx` picks up the callback route.

### Tools service cutover

GCP is stopped as of 2026-10; this is the plan for when it comes back. Do it in
this order, so no step leaves an agent without a working tool. The old
sidecars keep running until step 7.

1. **Deploy.** Create the secrets, then Release and Deploy (see
   [Releases and deploys](#releases-and-deploys)); Deploy runs
   `configure-env.sh`. For the cutover
   window, keep the old tools answering by setting
   `COMPOSE_PROFILES=remote,legacy-sidecars` in the VM's `.env` before the
   deploy. That starts `calendar-shim` and `chmarine-product-service` from
   the overlay's `legacy-sidecars` profile; their env files go in
   `deploy/gcp/secrets/`. The old api patch mounts are gone: their code ships
   in the images.
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

   Then set `COMPOSE_PROFILES=remote` again and run
   `sudo docker compose up -d --remove-orphans` in `/opt/lightmove/dograh`
   (or just the next Deploy). Events booked by the old shim
   carry no marker, so the agent cannot cancel them; cancel those in Google
   Calendar.

**Rollback:** set `COMPOSE_PROFILES=remote,legacy-sidecars`, run
`sudo docker compose up -d calendar-shim chmarine-product-service`, and
re-point the tools (re-running the two setup
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

## Billing (Stripe), email (Resend) and Google sign-in

All optional. `configure-env.sh` turns each on only when its secret exists,
and every Deploy runs it, so the next Deploy after creating a secret turns the
feature on. `dograh-app-sa` has no project-wide Secret Manager access, so grant
it each new secret (otherwise the script reports it as skipped and the feature
stays off):

```bash
# For each secret you use: paste the value at the prompt (keeps it out of
# shell history), then grant the VM's service account access.
for name in dograh-resend-api-key dograh-google-oauth-client-id dograh-google-oauth-client-secret; do
  echo "Paste $name, then Enter:"; read -rs V
  printf %s "$V" | gcloud secrets create "$name" --data-file=- --project=dograh-eu
  gcloud secrets add-iam-policy-binding "$name" --project=dograh-eu \
    --member=serviceAccount:dograh-app-sa@dograh-eu.iam.gserviceaccount.com \
    --role=roles/secretmanager.secretAccessor
done
unset V
# Stripe works the same way: dograh-stripe-secret-key (sk_...) and
# dograh-stripe-webhook-secret (whsec_...).

# Then run Deploy (the current version is fine once it includes the settings
# sync). Or, on the app VM:
cd /opt/lightmove/dograh
sudo ./deploy/gcp/configure-env.sh
sudo docker compose up -d api fallcha-tools
```

`up -d` recreates the containers with the new values; `docker compose restart`
does not re-read them. The sender defaults to
`LightMove.ai <no-reply@mail.lightmove.ai>`; `DOGRAH_EMAIL_FROM` changes it,
and later runs keep it. To turn Google sign-in and the platform client off, run
the script with `DOGRAH_GOOGLE=off` and delete the two secrets, or the next
Deploy turns them back on (a deleted secret looks the same to the VM as a
missing grant, so the script keeps the current values in that case). For the
other secrets `set_key` never
removes a key, so deleting one later also needs the matching lines removed
from `.env` by hand. A Secret Manager error other than "absent" or "not
readable" stops the script rather than switching a feature off.

**Rotating the Google client secret:** add the new secret in Google Auth
Platform, then `gcloud secrets versions add dograh-google-oauth-client-secret
--data-file=- --project=dograh-eu`, re-run the script, `sudo docker compose up -d api fallcha-tools`,
and only then disable the old secret in Google.

- **Stripe webhook:** add a dashboard endpoint at
  `https://<PUBLIC_BASE_URL>/api/v1/billing/stripe/webhook` with the five events
  listed in `docs/deployment/stripe-billing.mdx`. Its `whsec_` differs from the one
  `stripe listen` prints locally; store the dashboard one.
- **Resend:** the sending domain must be verified (SPF + DKIM records) before
  real users get mail. `onboarding@resend.dev` only reaches the Resend account
  owner.
- `UI_APP_URL` defaults to `PUBLIC_BASE_URL`, which is where emailed links and
  Stripe's return URLs land.
- **Google sign-in:** one Web OAuth client in this project (Google Auth Platform →
  Clients), user type External, published to Production (Testing only admits
  listed test users). Redirect URIs: `<PUBLIC_BASE_URL>/auth/google/callback` for
  sign-in, plus `<PUBLIC_BASE_URL>/oauth/google-calendar/callback` and
  `<PUBLIC_BASE_URL>/oauth/google-sheets/callback` when the same client also
  serves the Calendar and Sheets integrations. Sign-in asks only for
  `openid email profile`, which needs no Google review.

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
