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
| **Branding — 10 files, see below** | Renamed Dograh → Failte AI in the visible chrome |

#### Branding files

`ui/src/components/BrandLogo.tsx` (the only logo source — used by `AppSidebar` and `AuthShell`), `ui/src/app/layout.tsx` (page title), `ui/src/components/layout/AppLayout.tsx`, `ui/src/components/auth/AuthShell.tsx`, `ui/src/components/lead-forms/OnboardingModal.tsx`, `ui/src/app/overview/page.tsx`, `ui/src/components/Footer.tsx`, `ui/src/app/api-keys/page.tsx`, `ui/src/components/AIModelConfigurationV2Editor.tsx`, `ui/src/app/workflow/[workflowId]/components/WorkflowEditorHeader.tsx`.

**When resolving a conflict in these, the rename is intentional — keep our side of the branding strings and take upstream's side of everything else.**

Three rules were applied and should hold for any future branding work:

1. **Never rename wire values.** `mode: "dograh"` in the model configuration, `dograh_model` / `total_dograh_tokens` API fields, `window.DograhWidget` and `/embed/dograh-widget.js` (live on customer sites), the `dograh_auth_*` cookies and `X-Dograh-*` headers are all contracts. Only labels change.
2. **Upstream's hosted service is relabelled neutrally, not rebranded.** The "Managed models" tab and "Managed Service Keys" authenticate against `services.dograh.com`. Calling them Failte AI would claim we provide models we do not.
3. **Upstream's growth widgets are removed, not renamed.** The Slack invite to the Dograh community, the `dograh-hq/dograh` star badge (3 sites), the "Report an Issue" link to upstream's tracker, and the "Contact us" link into Dograh's sales funnel all pointed our users at the upstream project.

Still Dograh-branded by decision, not oversight: deep-page help text in tool configuration, telephony, usage ("Dograh Tokens") and file upload. Scope was limited to the chrome users read at a glance, to keep the merge cost down.

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

The suite is green. Any failure is ours:

```
1892 passed
```

At fork time it was `1858 passed, 2 failed`. Both failures were `api/tests/test_sdk_sync.py` — upstream's own drift, not ours: commit `871ad4cc` added `from_phone_number_id` to the trigger node spec without regenerating the SDKs, so the committed typed files no longer matched the spec registry. Release 1.45.0 shipped that way.

Fixed by regenerating **only** the typed node files — the two commands under step 1 of `scripts/generate_sdk.sh`:

```bash
source venv/bin/activate && set -a && source api/.env && set +a
SPECS=$(mktemp -t specs-XXXX.json)
python -m api.services.workflow.node_specs > "$SPECS"
PYTHONPATH="$PWD/sdk/python/src" python -m dograh_sdk.codegen --input "$SPECS" --out sdk/python/src/dograh_sdk/typed
node sdk/typescript/scripts/codegen.mts --input "$SPECS" --out sdk/typescript/src/typed
```

**Do not run the whole `scripts/generate_sdk.sh` for this.** Steps 2–5 rerun `datamodel-codegen`, `openapi-typescript` and the docs OpenAPI dump, regenerating large committed files with our local tool versions. Any version skew against what upstream committed becomes churn in `_generated_models.py`, `_generated_client.*` and `docs/api-reference/openapi.json` — a lot of new conflict surface for no benefit. Step 1 alone touches 2 files.

Expect `sdk/python/src/dograh_sdk/typed/trigger.py` and `sdk/typescript/src/typed/trigger.ts` to conflict once upstream regenerates their SDKs. **Take upstream's side** — theirs will be the correct output.
