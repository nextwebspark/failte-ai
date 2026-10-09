# fallcha-tools

Hosts Fallcha.ai's third-party tool providers (Google Calendar, Sheets, ...)
in one FastAPI service. Each workspace brings its own credentials; the
Fallcha API holds only an opaque connection key.

- `/internal/*` is called by the Fallcha API only. It requires
  `X-Internal-Secret` plus `X-Org-Id` / `X-User-Id`. It serves the provider
  catalog and manages connections and connection keys.
- `/mcp/{provider}` is a streamable-HTTP MCP server per provider. The voice
  engine calls it with `Authorization: Bearer <connection key>`. A key works
  only at its own provider's endpoint and only for its own connection.
- `/v1/{provider}/...` are optional plain-REST routes for `http_api` tools
  during migration. They take the same connection key, as `Authorization:
  Bearer <key>` or `X-API-Key: <key>`.
- Each connection has an encrypted `secret` and a non-secret `config`,
  validated by the provider's config model. `PATCH /internal/connections/{id}`
  with `{"config": {...}}` merges the given top-level keys into the stored
  config (omitted keys are kept), then validates the result.
- Secrets are Fernet-encrypted at rest. Everything lives in the Postgres
  schema `fallcha_tools`, with its own Alembic history; `public` is never
  touched.

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (`postgresql+asyncpg://...`; `postgresql://` is accepted) |
| `TOOLS_ENCRYPTION_KEYS` | Comma-separated Fernet keys. The first encrypts; all decrypt |
| `TOOLS_INTERNAL_SECRET` | Shared secret with the Fallcha API (16+ characters) |
| `TOOLS_PUBLIC_BASE_URL` | Public base URL, for OAuth callbacks |
| `LOG_LEVEL` | Default `INFO` |

Generate a key with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
To rotate, prepend a new key, re-encrypt with `SecretBox.rotate`, then drop
the old key.

## Run locally

```bash
uv venv tools/.venv --python 3.13
VIRTUAL_ENV=tools/.venv uv pip install -e 'tools[dev]'
cd tools
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
export TOOLS_ENCRYPTION_KEYS=... TOOLS_INTERNAL_SECRET=...
.venv/bin/alembic upgrade head                       # migrate
.venv/bin/uvicorn fallcha_tools.app:create_app --factory --port 8010
```

The Docker image runs `alembic upgrade head` on start; set
`RUN_MIGRATIONS=false` to skip it.

## Checks

```bash
cd tools
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --strict fallcha_tools
.venv/bin/pytest            # needs the fallcha_tools_test database
```

Tests use `TOOLS_TEST_DATABASE_URL` (default
`postgresql+asyncpg://postgres:postgres@localhost:5432/fallcha_tools_test`)
and refuse any database whose name does not end in `_test`. Create it once
with `docker exec <postgres container> createdb -U postgres fallcha_tools_test`.

## Google Calendar (`google-calendar`)

Ported from the single-tenant calendar shim; now per connection. Auth mode
`service_account` (OAuth2 comes later). Share the calendar with the service
account's email (*Make changes to events*), and the orders sheet, if used,
as Viewer.

```json
POST /internal/connections
{
  "provider": "google-calendar",
  "auth_mode": "service_account",
  "secret": { ...the service-account JSON key... },
  "config": {"calendar_id": "abc@group.calendar.google.com",
             "timezone": "Europe/Dublin", "event_summary_prefix": "Acme call",
             "orders_sheet_id": "<optional sheet id>"}
}
```

Other config fields (booking days, opening hours, slot length, buffer, lead
time, horizon, ...) default to the shim's values; `GET /internal/catalog`
returns the full JSON schema as `config_schema`.

| MCP tool | REST (`POST /v1/google-calendar/...`) |
|---|---|
| `check_appointment_availability(relative_day?, part_of_day?)` | `/availability` |
| `book_appointment(slot_id, caller_name, caller_phone, reason?)` | `/book` |
| `cancel_appointment(event_id)` (only events this connection booked) | `/cancel` |
| `look_up_order(caller_name, address_or_eircode, order_id?)` (read-only sheet) | `/order_lookup` |

REST bodies and responses match the shim's, so an existing `http_api` tool only
needs a new URL and a connection key in place of the old `X-API-Key`. Errors
are 400 (bad argument), 409 (not configured) or 502 (Google failure). Each
Google request times out after 4 s, and each tool call after 5 s.

Bookings use a deterministic event id (an HMAC of connection, slot and caller,
keyed by a subkey derived from `TOOLS_INTERNAL_SECRET`), so retrying
a booking whose reply was lost never creates a duplicate. Only slots between
the lead time and the horizon can be booked. Caller-facing errors never name
the service account; the connection test does, so admins know whom to share
the calendar with.

**Cutover from the shim:** `cancel_appointment` only cancels events this
connection booked (they carry a private marker). Events booked by the old
shim have no marker and cannot be cancelled through the agent; cancel them in
Google Calendar directly.

## Add a provider

1. Create `fallcha_tools/providers/<name>/` with a class that satisfies the
   `Provider` protocol in `fallcha_tools/core/provider.py`: `id`, `title`,
   `description`, `icon`, `auth_modes`, `scopes`, `config_model`,
   `validate_secret()`, `register_tools()`, `test_connection()` and
   `rest_router()` (return `None` for no REST routes).
2. In `register_tools(mcp, ctx_factory)`, declare tools with `@mcp.tool`.
   Inside each tool, `ctx = await ctx_factory()` gives the caller's
   `ConnectionContext`: org, connection, decrypted secret, access token and
   a shared `httpx.AsyncClient`, plus the connection's validated `config`.
3. Add an instance to `build_registry()` in `fallcha_tools/providers/__init__.py`.

The app mounts it at `/mcp/<id>` and lists it in `GET /internal/catalog`.
See `tests/echo_provider.py` for a minimal example and
`fallcha_tools/providers/google_calendar/` for a full one.
