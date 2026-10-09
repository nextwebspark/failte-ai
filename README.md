# Fallcha.ai

The Ireland-based voice agent platform ([fallcha.ai](https://fallcha.ai)). Build, test and deploy voice agents with a visual workflow builder, telephony, and your own choice of LLM / STT / TTS providers.

This repository is the platform itself — a private fork of [Dograh](https://github.com/dograh-hq/dograh) (BSD 2-Clause), extended into a multi-tenant SaaS. See [NOTICE.md](NOTICE.md) for attribution.

## Layout

| Path | What |
|---|---|
| `api/` | FastAPI backend — REST API, telephony, campaigns, ARQ workers |
| `ui/` | Next.js frontend — workflow builder, dashboard, agent editor |
| `pipecat/` | Voice pipeline (STT → LLM → TTS), a git submodule |
| `saas/` | Our own code and docs, kept out of upstream's tree |
| `deploy/` | Helm chart, nginx and coturn templates |

## Running it locally

Full setup, including the Python 3.13 requirement and the port remap this machine
needs, is in **[saas/docs/FORK.md](saas/docs/FORK.md)**. Once that is done:

```bash
# datastores
docker compose -f docker-compose-local.yaml \
               -f saas/dev/docker-compose-local.override.yaml up -d

# backend
source venv/bin/activate && bash scripts/start_services_dev.sh

# frontend
(cd ui && npm run dev)
```

UI on http://localhost:3000, API on http://localhost:8001.

Stop the backend with `bash scripts/stop_services.sh`; logs are in `logs/latest/`.

## Docs

| Doc | Covers |
|---|---|
| [saas/docs/FORK.md](saas/docs/FORK.md) | How this fork is maintained — branch model, the upstream sync runbook, which upstream files we are allowed to touch, local setup |
| [saas/docs/RBAC.md](saas/docs/RBAC.md) | The multi-tenant hierarchy: platform → vendor → client workspace → member |
| [saas/docs/AUTH-PROVIDER.md](saas/docs/AUTH-PROVIDER.md) | Auth provider evaluation under an EU data-residency constraint. Decision pending |

Upstream's documentation at [docs.dograh.com](https://docs.dograh.com) still describes
the platform's mechanics accurately and is worth reading for anything this repo's own
docs do not cover.

## Working on it

`main` is the product. Never push to the `upstream` remote — its push URL is
deliberately set to `DISABLED`. Before editing any file that came from upstream,
read the seam-file rules in [saas/docs/FORK.md](saas/docs/FORK.md): every line we
change in an upstream file is a conflict we pay for on every future sync.

Agents built on the platform live in their own repositories, not here. The Voiptel
inbound assistant is at `~/dev/voiptel-agent`.

## License

Upstream code is BSD 2-Clause — see [LICENSE](LICENSE). The Fallcha.ai additions in
this repository are proprietary; see [NOTICE.md](NOTICE.md).
