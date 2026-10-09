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

## Add a provider

1. Create `fallcha_tools/providers/<name>/` with a class that satisfies the
   `Provider` protocol in `fallcha_tools/core/provider.py`: `id`, `title`,
   `description`, `icon`, `auth_modes`, `scopes`, `register_tools()` and
   `test_connection()`.
2. In `register_tools(mcp, ctx_factory)`, declare tools with `@mcp.tool`.
   Inside each tool, `ctx = await ctx_factory()` gives the caller's
   `ConnectionContext`: org, connection, decrypted secret, access token and
   a shared `httpx.AsyncClient`.
3. Add an instance to `build_registry()` in `fallcha_tools/providers/__init__.py`.

The app mounts it at `/mcp/<id>` and lists it in `GET /internal/catalog`.
See `tests/echo_provider.py` for a minimal example.
