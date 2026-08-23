# Fork operations

This repository is a private fork of [dograh-hq/dograh](https://github.com/dograh-hq/dograh), the open-source voice AI platform, extended into a multi-tenant SaaS product. Upstream is under active development and we intend to keep merging from it, so everything below exists to keep that merge cheap.

Read this before your first change to a file that came from upstream.

## Licensing

Upstream is **BSD-2-Clause**. That permits closed-source derivatives and commercial use. Running the software as a hosted service is not distribution, so we have no source-release obligation.

What we must do: keep `LICENSE` intact and retain the upstream copyright notice. `NOTICE.md` at the repo root records the derivation and our own copyright over the SaaS layer.

## Remotes

| Remote | URL | Push |
|---|---|---|
| `origin` | `https://github.com/nextwebspark/failte-ai.git` | yes |
| `upstream` | `https://github.com/dograh-hq/dograh.git` | **disabled** |

The upstream push URL is deliberately set to the literal string `DISABLED` so an accidental `git push upstream` fails loudly instead of attempting to publish our proprietary code to a public repo:

```bash
git remote set-url --push upstream DISABLED
```

Verify with `git remote -v` after any clone. A fresh clone of this repo does **not** inherit the `upstream` remote — re-add it and re-apply the guard.

The repo was seeded with `git clone --mirror` + `git push --mirror`, so full upstream history, all 209 branches and all 53 tags are present. GitHub rejects `refs/pull/*` on push; those are server-managed read-only refs and their absence is expected, not data loss.

Do **not** run `scripts/setup_fork.sh` — it is upstream's contributor bootstrap and will try to repoint `origin` at a public fork.

## Branches

| Branch | Role |
|---|---|
| `main` | Our product: upstream code plus the SaaS layer. Deployable. |
| `vendor/upstream` | Pristine mirror of `upstream/main`. **Never edited.** Fast-forward only. |
| `sync/upstream-YYYY-MM-DD` | One per upstream sync. Merged into `main` via PR. |
| `feat/*` | Feature branches off `main`. |

`vendor/upstream` earns its keep two ways: it gives merges a clean three-way base, and `git diff vendor/upstream main` is an honest, complete answer to "what have we actually changed?"

## Syncing with upstream

Run every 2–4 weeks. Upstream pushes frequently, and small merges are much cheaper than large ones.

```bash
git fetch upstream --tags
git checkout vendor/upstream && git merge --ff-only upstream/main && git push origin vendor/upstream
git checkout -b sync/upstream-$(date +%F) main
git merge vendor/upstream          # resolve conflicts HERE, never on main
bash scripts/lint.sh
source venv/bin/activate && set -a && source api/.env.test && set +a && python -m pytest api/tests
# then open a PR into main
```

**Merge, never rebase.** Rebasing our work onto upstream rewrites our history and forces us to re-resolve the same conflicts every single cycle. A merge records each resolution once.

`git config rerere.enabled true` is set in this clone — git replays previously-seen conflict resolutions automatically. Re-run it in any fresh clone.

## Where our code goes

**New code goes in new directories. Upstream files are touched only at seams, and minimally.** Every line we add to an upstream file is a conflict we will pay for on every future sync. Every file we add is free.

```
saas/docs/     design docs (this file, RBAC.md, AUTH-PROVIDER.md)
saas/dev/      local dev config that is ours, not upstream's
api/saas/      backend: tenancy, RBAC, provisioning, billing
ui/src/saas/   frontend: admin consoles, vendor/client switchers
```

### Seam files

These upstream files we expect to modify. Keep this list short and current — adding an entry should be a deliberate decision, not a side effect.

| File | Why it must be touched |
|---|---|
| `api/services/auth/depends.py` | `get_user` / `get_superuser` — the single point where identity and (soon) tenant + role context attach to a request |
| `api/db/models.py` | `organization_users` association table, `OrganizationModel`, `UserModel` — the hierarchy and role columns land here |
| `api/routes/main.py` | One `include_router` line per new router. Append at the end; conflicts are then trivial |
| `ui/src/middleware.ts` | Route guarding by role |
| `ui/src/lib/auth/` | Provider abstraction (`types.ts`, `config.ts`, `providers/`) |
| **Branding — every user-visible string, see below** | Renamed Dograh → Failte AI, or removed |
| `api/routes/user.py` | Google voice catalogue: a `provider == "google"` branch before the MPS call, the `/voices/google/preview` route, and `"google"` added to the `TTSProvider` literal |
| `ui/src/components/VoiceSelectorModal.tsx` | Authenticated blob playback (plus revocation) for our own relative preview URLs, and `defaultGender`/`defaultAccent`/`defaultLanguage` props so a provider can open on something other than American English |
| `ui/src/components/ServiceConfigurationForm.tsx` | A Google TTS voice field renders `VoiceSelectorModal`, ahead of the `allow_custom_input` check |
| `ui/src/client/` | Regenerated — the voice route's provider path param now includes `google` |
| `api/services/pipecat/service_factory.py` | Google TTS: `language_code` derived from the voice's own locale instead of the separately-configured language. Vertex LLM: the `GOOGLE_VERTEX` branch is a single call into fork-owned `api/services/pipecat/vertex_llm.py`, which routes Claude/MaaS models to their own services |
| `api/services/configuration/options/google.py` | `GOOGLE_VERTEX_MODELS` extended with Claude and MaaS ids after upstream's Gemini block — keep both halves on conflict |
| `api/services/configuration/registry.py` | Vertex `model`/`location` field descriptions widened to cover Claude and MaaS |
| `api/Dockerfile`, `.devcontainer/Dockerfile`, `scripts/setup_pipecat.sh`, `scripts/setup_requirements.sh`, `scripts/setup_requirements.ps1` | `anthropic` added to the pipecat extras list — five copies of one string; re-add it to any site upstream rewrites |
| `api/tests/test_google_tts_service_factory.py` | One fixture paired `sw-KE` with an `en-US` voice — the combination Google rejects — so it had to become a consistent pair |
| `ui/src/app/workflow/[workflowId]/run/[runId]/hooks/useWebSocketRTC.tsx` | Live-feedback row ids come from `@/lib/feedbackId` — `Date.now()` alone collides |
| `ui/src/lib/publicEmbedWidget.test.ts` | The mocked embed config carries a `texts` block, as the real endpoint does |

#### Google voice picker

The logic lives in `api/saas/voice_catalog/google_voices.py` (ours, conflict-free); the three
files above are the seams that reach it. Upstream serves voice catalogues from its hosted MPS
service, which has no Google voices, so a BYOK Google deployment got a free-text voice id box.

Google reuses `VoiceSelectorModal` — the dialog upstream built for its managed pipeline, which
filters server-side on `gender`/`accent`/`language`/`q` and reads `facets` back. Our catalogue
answers exactly that contract, so agent-level Google voice selection is wiring, not new UI.
`VoiceSelector` (the popover used by the MPS providers) is deliberately left untouched.

Three traps worth keeping in the resolution:

- Google's voice field sets `allow_custom_input: true`, and the form only rendered a picker when
  a field *disallowed* it. Without the `ServiceConfigurationForm` change the modal is unreachable.
- An `<audio>` element can send neither a backend origin nor a bearer token, so our preview URLs
  must be fetched and played as a blob. MPS previews are public URLs and need none of this.
- Voices carry a *base* language (`en`) with the region in `accent` (`gb`), not the raw locale
  (`en-GB`). The picker's language filter and `LANGUAGE_DISPLAY_NAMES` are both keyed on the base
  code, so emitting locales makes the default filter match zero voices. `preview_audio()`
  recovers the full locale from the voice id.
- Google's synthesis call takes `language_code` and `voice` separately and rejects them if they
  disagree (`en-GB` + `en-US-Chirp3-HD-Aoede` is a 400). Since the two are configured
  independently, `service_factory.py` takes the language from the voice's locale prefix and falls
  back to the configured one only for a voice that carries none.

Covered by `api/tests/test_google_voice_catalog.py`, `api/tests/test_google_tts_service_factory.py`
and `ui/src/components/VoiceSelectorModal.test.tsx`.

#### Branding

The de-branding pass covers **every string, link and asset a user can read or click** in `ui/`, not just the chrome. Do not re-narrow it. When resolving a conflict in a touched file, the rename is intentional — keep our side of the branding strings and take upstream's side of everything else.

Five rules, to hold for any future branding work:

1. **Never rename wire values.** `mode: "dograh"` in the model configuration, `dograh_model` / `total_dograh_tokens` API fields, the `dograh_auth_*` cookies and `X-Dograh-*` headers are all contracts. Only labels change.
2. **Upstream's hosted service is relabelled neutrally, not rebranded.** The "Managed models" tab and "Managed Service Keys" authenticate against `services.dograh.com`. Calling them Failte AI would claim we provide models we do not.
3. **Upstream's growth widgets are removed, not renamed.** The Slack invite, the `dograh-hq/dograh` star badge, the "Report an Issue" link and the sales-funnel "Contact us" all pointed our users at the upstream project.
4. **No documentation links.** We publish no docs site. `ui/src/constants/documentation.ts` is deleted; documentation URLs the API supplies inside provider schemas and node specs are filtered by `ui/src/lib/externalDocs.ts`, which drops `*.dograh.com` and lets genuine third-party provider docs (Azure, Inworld, Hugging Face, Google STT) through. A sync that adds another vendor-hosted `docs_url` needs no new edit; a sync that reintroduces a hardcoded `docs.dograh.com` anchor must have it deleted.
5. **No lead-gen.** `ui/src/components/lead-forms/` (17 files), `ui/src/context/LeadFormsContext.tsx` and `AuthEnterpriseCTA` are deleted — they POSTed our users' PII to `api-leads.dograh.com`. The post-signup onboarding questionnaire went with them. If a sync reintroduces any of it, delete it again. Support is a `mailto:` from `ui/src/components/SupportLink.tsx`, and the Chatwoot bubble (which routed our users into the upstream vendor's helpdesk) is deleted along with its `NEXT_PUBLIC_CHATWOOT_*` defaults in `ui/Dockerfile`.

**Embed widget.** The widget is `ui/public/embed/failte-widget.js` and its global is `window.FailteWidget`. `dograh-widget.js` remains as a shim that re-injects the real file, and the widget itself still accepts `data-dograh-context`, the legacy `dograh-inline-container` id and `window.DograhWidget` as an alias. That backward compatibility exists for snippets already pasted on customer sites — **do not delete it**. The snippet is generated server-side in `api/routes/workflow_embed.py`; it and the widget must be renamed in the same release.

Accepted residue, checked and left alone: the Axiom org slug `dograh-of6c` in the superadmin-only log link, the GHCR image names behind the update badge, `ui/src/client/*.gen.ts` (generated from the API's OpenAPI spec — a hand edit gets clobbered), and comments that record what upstream shipped and why it was removed. Those comments are what stops a future sync from silently re-adding the growth widgets.

Not done, and a deliberate scope call: user-visible strings produced by `api/` and merely echoed by the UI — `api/services/quota_service.py` messages, `api/errors/*.py` external messages, `api/services/organization_bootstrap.py`'s `"Default Dograh Model Service Key"` (also already written into provisioned orgs' rows), and the OpenAPI title/servers in `api/app.py` that seed `client.gen.ts`. Fix those at the API when the appetite for an `api/` diff exists.

Prefer adding a new module over editing an existing one. Upstream's `AUTH_PROVIDER` seam is explicitly designed for this — a new provider drops in beside `local` and `stack` without touching either. See `docs/deployment/authentication.mdx`.

### Alembic migrations

Upstream appends revisions to `api/alembic/versions/` on a linear chain. Ours branch off whatever head existed when we wrote them, so **after a sync there will be two heads**. This is normal:

```bash
alembic heads                                            # shows 2
alembic merge -m "merge upstream migrations" <h1> <h2>
alembic upgrade head
```

Prefix our revision messages with `saas_` so ours are greppable in a directory upstream also writes to. Never edit an upstream revision file — rewrite history in the DB and you break every existing deployment.

### Generated code

`ui/src/client/` is generated from the backend OpenAPI spec (`ui/openapi-ts.config.ts`, `scripts/generate_sdk.sh`). Regenerate after adding routes. Hand edits get clobbered and conflict.

### CI

Upstream's `.github/workflows/` includes `release-please` and Slack announcements wired to *their* infrastructure. On `main`: disable or repoint `release-automation.yml`, `release-deployment.yml`, `slack-announcements.yml`. **Keep `api-tests.yml`** — it is our regression signal against every upstream merge. Add our own deploy workflow as a new file rather than editing theirs.

## The pipecat submodule

`.gitmodules` points at `https://github.com/dograh-hq/pipecat.git` (itself a fork of `pipecat-ai/pipecat`). **Decision: leave it pointing upstream.** Editing `.gitmodules` creates a conflict on every submodule bump, and we have no reason to patch the voice pipeline.

If we later need pipecat changes, mirror that repo the same way and repoint then. Open item, not a current one.

## Local development

Host-managed setup (not the devcontainer). See `docs/contribution/reference.mdx` for upstream's version; the fork-specific deltas are here.

**Python must be 3.13** — `api/pyproject.toml` pins `>=3.13,<3.14`, and 3.14 will not work. Installed via `brew install python@3.13`.

```bash
git submodule update --init --recursive
/opt/homebrew/bin/python3.13 -m venv venv
source venv/bin/activate                      # required BEFORE the next line
bash scripts/setup_requirements.sh --dev
(cd ui && npm install)
(cd api/mcp_server/ts_validator && npm ci)    # NOT in upstream's host-managed docs
```

`scripts/setup_requirements.sh` resolves `python3` from `PATH`, so running it without an activated venv silently targets the system interpreter and fails the version check. Activate first.

The `ts_validator` install is easy to miss: the devcontainer bootstrap runs it, but upstream's host-managed instructions do not mention it. Skip it and 27 tests fail (`test_ts_bridge.py`, `test_mcp_save_workflow.py`) for a reason that looks like a code problem and is not.

### Port remapping

This machine already runs a separate Dograh deployment at `/Users/alokkumar/dev/voice-agent` (prebuilt `ghcr.io` images) holding ports 5432, 6379, 9000/9001 and 8000. The fork's datastores are therefore remapped by `saas/dev/docker-compose-local.override.yaml`:

| Service | Upstream default | Fork |
|---|---|---|
| Postgres | 5432 | **5433** |
| Redis | 6379 | **6380** |
| MinIO API / console | 9000 / 9001 | **9002 / 9003** |
| API (uvicorn) | 8000 | **8001** |
| UI | 3000 | 3000 (free — the other stack uses 3010) |

Start them with both files. The override is **not** auto-loaded: Docker only auto-applies `docker-compose.override.yaml` to `docker-compose.yaml`, and we are overriding `docker-compose-local.yaml`.

```bash
docker compose -f docker-compose-local.yaml \
               -f saas/dev/docker-compose-local.override.yaml up -d
```

The override uses the `!override` YAML tag on each `ports` list. Without it Compose *appends* sequence fields, the base file's 5432/6379/9000 bindings survive, and the containers still collide.

### Environment files

```bash
bash saas/dev/bootstrap-env.sh
```

Creates the three env files from upstream's templates, applies the port remap, generates an `OSS_JWT_SECRET`, and points the UI at our backend. Idempotent — existing files are left alone, but the port-critical values are re-enforced on every run.

Also create the test database once, after the postgres container is up:

```bash
docker compose -f docker-compose-local.yaml \
               -f saas/dev/docker-compose-local.override.yaml \
               exec postgres createdb -U postgres test_db
```

The values that matter in `api/.env`:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5433/postgres` |
| `REDIS_URL` | `redis://:redissecret@localhost:6380` |
| `MINIO_ENDPOINT` | `localhost:9002` |
| `MINIO_PUBLIC_ENDPOINT` | `http://localhost:9002` |
| `UVICORN_BASE_PORT` | `8001` |
| `BACKEND_API_ENDPOINT` | `http://localhost:8001` |
| `OSS_JWT_SECRET` | random hex — **required**, the stack will not start without it |

Two traps worth knowing, both of which cost time here:

- The variable is **`UVICORN_BASE_PORT`**, not `UVICORN_PORT`. `scripts/start_services_dev.sh:39` reads the former (`scripts/run_web.sh` uses `WEB_PORT` — a third name, for the production path). Set the wrong one and uvicorn tries to bind 8000, dies with `[Errno 48] Address already in use`, **and the launcher's health check passes anyway** — because the *other* Dograh deployment on 8000 answers it. Always confirm the reported health-check URL says 8001.
- `api/.env.test` deliberately targets a **separate database** (`test_db`). Remap only the host:port when adjusting it; overwriting `DATABASE_URL` wholesale points the entire test suite at the dev database, and pytest will happily wipe it.

Hosts stay on `localhost` here. The docker-network-alias rewrite (`postgres`, `redis`, `minio`) described in upstream's reference doc applies only inside the devcontainer.

### Running

```bash
source venv/bin/activate
bash scripts/migrate.sh
bash scripts/start_services_dev.sh     # waits for health, prints a summary
(cd ui && npm run dev)
```

Backend logs: `tail -f logs/latest/*.log`. Stop with `bash scripts/stop_services.sh`.

### Canary tests

Run these after every upstream sync and before every auth/tenancy change:

```bash
source venv/bin/activate && set -a && source api/.env.test && set +a
python -m pytest api/tests/test_auth_depends.py api/tests/test_organization_bootstrap.py
```

They cover exactly the code paths our SaaS layer extends.

### Test baseline

Both suites are green. Any failure is ours:

```
python -m pytest api/tests   ->  1911 passed
cd ui && npm test            ->  106 passed (21 files)
```

At fork time it was `1858 passed, 2 failed`. Both failures were `api/tests/test_sdk_sync.py` — upstream's own drift, not ours: commit `871ad4cc` added `from_phone_number_id` to the trigger node spec without regenerating the SDKs, so the committed typed files no longer matched the spec registry. Release 1.45.0 shipped that way.

The UI suite also inherited one failure: `publicEmbedWidget.test.ts` mocked the embed config
endpoint without its `texts` block, and the widget holds no default copy of its own — every
visitor-facing string arrives already resolved from `api/schemas/widget_texts.py`. So
`widgetText()` returned `''` for every key and the banner the test asserts on rendered empty.
Fixed in the fixture, which now sends `texts` the way the real endpoint does.

The SDK drift was fixed by regenerating **only** the typed node files — the two commands under step 1 of `scripts/generate_sdk.sh`:

```bash
source venv/bin/activate && set -a && source api/.env && set +a
SPECS=$(mktemp -t specs-XXXX.json)
python -m api.services.workflow.node_specs > "$SPECS"
PYTHONPATH="$PWD/sdk/python/src" python -m dograh_sdk.codegen --input "$SPECS" --out sdk/python/src/dograh_sdk/typed
node sdk/typescript/scripts/codegen.mts --input "$SPECS" --out sdk/typescript/src/typed
```

**Do not run the whole `scripts/generate_sdk.sh` for this.** Steps 2–5 rerun `datamodel-codegen`, `openapi-typescript` and the docs OpenAPI dump, regenerating large committed files with our local tool versions. Any version skew against what upstream committed becomes churn in `_generated_models.py`, `_generated_client.*` and `docs/api-reference/openapi.json` — a lot of new conflict surface for no benefit. Step 1 alone touches 2 files.

Expect `sdk/python/src/dograh_sdk/typed/trigger.py` and `sdk/typescript/src/typed/trigger.ts` to conflict once upstream regenerates their SDKs. **Take upstream's side** — theirs will be the correct output.
