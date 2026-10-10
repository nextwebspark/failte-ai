# Hostinger (managed-Traefik) deployment

Deploy Dograh where a shared, managed Traefik with Let's Encrypt already
terminates TLS and routes ingress — e.g. **Hostinger's VPS Docker Manager**.
The same files work on any host that fronts containers with Traefik.

## Files

| File | Role | Deploy on Hostinger? |
|---|---|---|
| `docker-compose.yaml` | The Dograh app stack. **Single self-contained file** — named volumes only, no host bind-mounts, no init/sidecar that reads files outside the compose. | ✅ Yes |
| `.env.example` | Required + optional environment variables, with guidance. Copy to `.env` and fill in. | ✅ Yes (as the env template) |
| `docker-compose.traefik.yaml` | A standalone Traefik + Let's Encrypt that **stands in for** the managed Traefik, so you can reproduce the environment on a plain VPS for testing. Also documents what the platform's Traefik must provide. | ❌ **No — reference only** |

## What the app stack needs from Traefik

Routing is declared with Traefik labels on `ui`, `api`, and `minio`:
`/api/v1` → api (includes the signaling **WebSocket**), `/voice-audio` → minio,
everything else → ui. For that to work the platform's Traefik must offer:

- an HTTPS entrypoint — set `TRAEFIK_ENTRYPOINT` (e.g. `websecure`)
- a Let's Encrypt certresolver — set `TRAEFIK_CERTRESOLVER`
- the Docker provider watching a shared network — set `TRAEFIK_NETWORK`
- a long `idleTimeout` so long-lived signaling WebSockets aren't cut
- (recommended) a global HTTP→HTTPS redirect

Traefik upgrades WebSockets automatically — no special label is required.

## WebRTC media (coturn) is NOT proxied by Traefik

Voice audio is UDP (ICE/DTLS-SRTP), relayed by the bundled `coturn`. A reverse
proxy cannot carry it. coturn publishes host ports that **must be open in the
VPS firewall**: UDP+TCP `3478` and `5349`, and UDP `49152-49200`. `TURN_HOST`
must be the public IP (or a domain resolving to it). Without this, calls
connect (signaling succeeds) but have **no audio**.

## Deploy on Hostinger

The platform provides Traefik, so you only deploy the app stack:

1. Copy `.env.example` → `.env` and fill in `PUBLIC_HOST`, `TURN_HOST`, the
   secrets, and the three `TRAEFIK_*` values (matched to Hostinger's Traefik).
2. Import / deploy `docker-compose.yaml`.
3. Ensure the coturn UDP/TCP ports above are open in the firewall.

## Test on a generic VPS (self-managed stand-in Traefik)

On a box that does **not** already run Traefik:

```bash
cp .env.example .env     # fill in PUBLIC_HOST, TURN_HOST, secrets, ACME_EMAIL
docker network create traefik-proxy
docker compose -f docker-compose.traefik.yaml --env-file .env up -d   # stand-in Traefik
docker compose --env-file .env up -d                                  # app stack
```

A no-cost trick for a real cert without owning a domain: set
`PUBLIC_HOST=<public-ip>.sslip.io` (sslip.io resolves any embedded IP), which
Let's Encrypt will happily issue for.

## Integrations (fallcha-tools) are not part of this stack

This self-contained stack is the upstream Hostinger variant. It does not
run the `fallcha-tools` service, so the Integrations page reports
"Integrations aren't configured on this server". To add it:

- Copy the `fallcha-tools` service from the root `docker-compose.yaml`.
- Set `TOOLS_INTERNAL_SECRET` and `CREDENTIALS_ENCRYPTION_KEYS` on `api`.
- Route only the OAuth callback to the tools service, on both the
  `app-network` and `traefik` networks:

```yaml
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=${TRAEFIK_NETWORK:-traefik-proxy}"
      - "traefik.http.routers.fallcha-oauth.rule=Host(`${PUBLIC_HOST}`) && Method(`GET`) && PathRegexp(`^/oauth/[a-z0-9-]+/callback$$`)"
      - "traefik.http.routers.fallcha-oauth.entrypoints=${TRAEFIK_ENTRYPOINT:-websecure}"
      - "traefik.http.routers.fallcha-oauth.tls=true"
      - "traefik.http.routers.fallcha-oauth.tls.certresolver=${TRAEFIK_CERTRESOLVER:-letsencrypt}"
      - "traefik.http.routers.fallcha-oauth.priority=30"
      # Pin the forwarded path to the clean callback (the query is kept), so
      # dot segments or encoded slashes in the raw URL never reach another route.
      - "traefik.http.routers.fallcha-oauth.middlewares=fallcha-oauth-path"
      - "traefik.http.middlewares.fallcha-oauth-path.replacepathregex.regex=^/oauth/([a-z0-9-]+)/callback$$"
      - "traefik.http.middlewares.fallcha-oauth-path.replacepathregex.replacement=/oauth/$$1/callback"
      - "traefik.http.services.fallcha-oauth.loadbalancer.server.port=8000"
```

`$$` is Compose's escape for a literal `$`. The router only matches the
callback path, and the `ReplacePathRegex` middleware forwards the path rebuilt
from the provider id. The tools service also answers 400 to any path with
`..`, `%2e`, `%2f` or `%5c` in it.

Traefik's access log is off by default. If you turn it on, drop the query
string for this router: it carries the OAuth authorization code.
