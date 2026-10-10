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
- `/oauth/{provider}/callback` is the only public route: the OAuth2
  provider redirects the user's browser here (see [OAuth2](#oauth2-bring-your-own-client)).
- `/v1/{provider}/...` are optional plain-REST routes for `http_api` tools
  during migration. They take the same connection key, as `Authorization:
  Bearer <key>` or `X-API-Key: <key>`.
- Each connection has an encrypted `secret` (none for the `none` auth mode,
  used by providers that only read public data) and a non-secret `config`,
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
| `TOOLS_PUBLIC_BASE_URL` | Public URL that reaches this service's `/oauth/*` (may include a path prefix, e.g. `https://app.example.com/tools`). OAuth is off (503) until set |
| `TOOLS_UI_RETURN_URL` | Fixed UI page the OAuth callback redirects back to (e.g. `https://app.example.com/integrations`). OAuth is off (503) until set |
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
.venv/bin/mypy --strict fallcha_tools tests
.venv/bin/pytest            # needs the fallcha_tools_test database
```

Tests use `TOOLS_TEST_DATABASE_URL` (default
`postgresql+asyncpg://postgres:postgres@localhost:5432/fallcha_tools_test`)
and refuse any database whose name does not end in `_test`. Create it once
with `docker exec <postgres container> createdb -U postgres fallcha_tools_test`.

## Google Calendar (`google-calendar`)

Ported from the single-tenant calendar shim; now per connection, and
calendar-only (order lookup moved to [Google Sheets](#google-sheets-google-sheets)).
Auth modes `service_account` and `oauth2` (see below). With a service
account, share the calendar with the service account's email (*Make changes
to events*).

```json
POST /internal/connections
{
  "provider": "google-calendar",
  "auth_mode": "service_account",
  "secret": { ...the service-account JSON key... },
  "config": {"calendar_id": "abc@group.calendar.google.com",
             "timezone": "Europe/Dublin", "event_summary_prefix": "Acme call"}
}
```

Other config fields (booking days, opening hours, slot length, buffer, lead
time, horizon, ...) default to the shim's values; `GET /internal/catalog`
returns the full JSON schema as `config_schema`. A service-account
connection is labelled with the key's `client_email`.

| MCP tool | REST (`POST /v1/google-calendar/...`) |
|---|---|
| `check_appointment_availability(relative_day?, part_of_day?)` | `/availability` |
| `book_appointment(slot_id, caller_name, caller_phone, reason?)` | `/book` |
| `cancel_appointment(event_id)` (only events this connection booked) | `/cancel` |

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
Google Calendar directly. The shim's `/order_lookup` is now
`POST /v1/google-sheets/order_lookup` on a **Google Sheets** connection, so
the Voiptel agent needs two integrations: Google Calendar (bookings) and
Google Sheets (orders, `orders_tab` set). With a service account, connect
Calendar first and let Sheets reuse the same key (see
[Auth families](#auth-families-and-reuse)).

## Google Sheets (`google-sheets`)

One spreadsheet per connection. Auth modes `service_account` (share the
spreadsheet with the service account's email as *Editor*, so rows can be
added; *Viewer* is enough for lookups) and `oauth2`.

**Scope.** `https://www.googleapis.com/auth/spreadsheets` (read and write):
`append_row` needs write access and Google has no narrower scope that allows
appending to one sheet only. There are no optional scopes. `look_up_order`
reads with a `spreadsheets.readonly` token (service accounts), so that
function can never write.

| Config | Default | |
|---|---|---|
| `spreadsheet_id` | required | The id, or the full `docs.google.com` URL |
| `default_tab` | first allowed tab, else the first tab | Tab used when a call names none |
| `allowed_tabs` | all | If set, tools may only read and write these tabs (checked before any Google call) |
| `max_rows_returned` | 20 | Most rows `find_rows` returns (1-100) |
| `header_row` | 1 | Row holding the column names; data starts below |
| `orders_tab` | unset (lookup off) | Tab read by `look_up_order` (whether or not it is in `allowed_tabs`) |
| `generic_tools_read_orders` | false | Let `find_rows`/`get_row`/`append_row` use the orders tab too; off, it is reachable only through the verified lookup |
| `order_columns` | the shim's headers | Header names for `order_id`, `customer_name`, `address`, `eircode`, `package`, `status`, `eta`, `hardware`, `order_date`, `monthly_price` |

| MCP tool | |
|---|---|
| `find_rows(column, value, tab?, match)` | Rows whose column matches (`exact` or `contains`; case and spacing ignored), as header -> value, up to `max_rows_returned`; `more` says if others matched. Scans 10,000 rows below the header |
| `get_row(row_number, tab?)` | One row by sheet row number (a row past the end of the sheet is "not found") |
| `append_row(values, tab?)` | Adds a row, `{column: value}` mapped by header name; unknown columns are rejected |
| `look_up_order(caller_name, address_or_eircode, order_id?)` | The shim's verified order lookup (REST: `POST /v1/google-sheets/order_lookup`, same body and response) |

Each call runs under a 5 s budget (each request gets what is left; a hard
stop follows shortly after). Ranges are A1-quoted (`'Leads'!1:1`, quotes in
tab names doubled) and URL-encoded.

**Values are written RAW** (`valueInputOption=RAW`): Sheets stores exactly
the text the agent sent and never parses it as a formula, number or date,
so the caller's words cannot become a formula in the sheet and dates are
not reinterpreted by locale. Because the sheet may later be exported to CSV
or Excel, where a leading `=`, `+`, `-`, `@`, tab or carriage return starts a
formula (CSV injection), such values are stored with a leading apostrophe
(visible in the cell, since RAW keeps it literally: the trade-off for
never parsing input). The one exception is a
plain international phone number (`+353 87 123 4567`), which cannot call a
function and is the most common value a voice agent writes. With
`USER_ENTERED` the apostrophe would be hidden, but the agent's text would be
parsed (formulas, dates, numbers), which is what RAW avoids.

`append_row` is not idempotent: if Google does not answer in time, the tool
says the row may have been added rather than inviting a retry.

**Order lookup** is unchanged from the shim: the caller must match both the
account name (0.72 similarity, surname alone allowed) and the address or
Eircode (0.62; an Eircode match wins); a miss gives the same answer whatever
did not match; rows are cached for 60 s per connection and tab; only order
fields (never phone, full address or notes) are returned.

Calendar connections saved before order lookup moved here may still carry
`orders_sheet_id` / `orders_tab`: migration 0006 strips them, and the
calendar config model ignores them, so such connections keep working (set
the orders up again on a Sheets connection).

## Website catalogue (`website-catalogue`)

A generic port of the CH Marine `product_service`: any shop whose product
pages publish schema.org `Product` JSON-LD and are listed in a sitemap. CH
Marine is just a connection with its site URL. Auth mode `none` (public
data, no secret); tool calls still need the connection key.

| Config | Default | |
|---|---|---|
| `site_url` | required | The shop's home page (public domain name, http/https) |
| `sitemap_url` | robots.txt `Sitemap:` lines, else `/sitemap.xml` | Sitemap or sitemap index, on the site's own host |
| `currency` | `EUR` | Used when a page states none |
| `include_paths` | all pages | Path prefixes, or `*` globs, e.g. `/products/` |
| `max_products` | 2000 | Most product pages fetched per sync |
| `request_delay_seconds` | 1.0 | Pause between request starts (a longer robots.txt `Crawl-delay` wins, capped at 60 s) |
| `max_concurrency` | 2 | Parallel requests (1-4) |
| `max_sync_minutes` | 30 | A sync still running after this long is stopped (failed) |
| `max_results` | 3 | Products named per answer (never more than 5) |
| `no_match_transfer_offer` | "I can also put you through to one of the team." | Appended to the no-match answer; empty for none |

**Sync.** `POST /internal/connections/{id}/sync` (Fallcha:
`POST /api/v1/integrations/connections/{id}/sync`, `INTEGRATIONS_WRITE`)
returns 202 and imports in the background, under a per-connection
session-level advisory lock: a second request while one runs (in any
replica) gets 409, and a process allows at most 4 concurrent syncs. The
connection's `sync` field reports `status` (`running`, `succeeded`,
`failed`), `item_count`, `last_synced_at` and `last_error`; a running sync
whose heartbeat is over 5 minutes old (the process died) reads as failed;
the heartbeat is refreshed while sitemaps and every page are processed,
whether or not they hold products. After a sync, the catalogue is what its
sitemaps listed (capped at `max_products`): other products are removed,
while pages that failed to load keep their previous data. A successful sync
reports caveats in `note` ("stopped at 2000 pages", "3 page(s) could not be
loaded"). One page that cannot be fetched or parsed (timeout, bad markup,
over-deep JSON) is counted and skipped; a storage error stops the whole
sync, cancelling the pages in flight. The Fallcha UI starts the first
sync when the connection is made.

**Polite crawling.** An honest `FallchaCatalogueBot/1.0` User-Agent; robots.txt
is honoured (401/403: nothing may be crawled; other 4xx: no rules; 5xx:
stop); pages (2 MB, 30 s each including the body), sitemaps (20 MB, 60 s,
gzip inflated with a cap) and robots.txt have size and time caps; only
`Accept-Encoding: gzip` is offered; pages are parsed in a worker thread;
sitemap indexes are followed (product sitemaps first, at most 50); only
sitemaps and pages on the site's host (with or without `www.`) are used.

**SSRF protection** (`fallcha_tools/core/netguard.py`). Every fetch accepts
only http/https URLs on ports 80/443/8080/8443 without credentials, resolves
the host and refuses it unless every address is public (no private,
loopback, link-local, CGNAT, multicast, reserved or unspecified addresses,
including IPv4 addresses embedded in IPv6: mapped, 6to4, NAT64
`64:ff9b::/96` and IPv4-compatible `::/96`), follows at most 5 redirects itself
and checks each hop, ignores proxy environment variables, and connects
through a network backend that re-resolves the host and connects to the
vetted IPs (each in turn) (TLS still verifies the host name), so DNS rebinding cannot reach
an internal address.

**Storage.** `fallcha_tools.catalogue_products` (one row per connection and
SKU, with `org_id`), a generated weighted `tsvector` (name A, brand B,
category C, description D; `english` stemming) and a GIN index. Every query
filters on org and connection. No SQLite.

| MCP tool | REST (`POST /v1/website-catalogue/...`) |
|---|---|
| `search_products(query, max_results?)` | `/product_search` |
| `product_detail(sku)` | `/product_detail` |

Requests and responses match the original service (a miss omits
`unmatched_terms`; `max_results` above 5 is capped), so the CH Marine
`http_api` tools only need the new URL and the connection key as
`X-API-Key`.

**Parity with the original `product_service`:**

- Same answers: spoken prices ("twenty-nine euro ninety-five"), stock
  phrases, "I have ..." / "I could not find that exact one, but I do have
  ..." when a word matched nothing, and the same no-match sentence.
- Same search rules: filler words and words under 3 letters dropped; words
  absent from the catalogue reported as unmatched; AND first, then OR when
  AND finds nothing worth reading; hits must carry a caller word in the
  name or brand (the same crude plural stemming) unless they are a strong
  description-only match; name/brand hits sort first.
- Different: the original's "strong description match" was a bm25 score
  cutoff (-5). Postgres ranks are on another scale and could not separate
  the original's own examples ("something to clean the hull" vs. "anchors
  for a small boat"), so a description-only hit counts as strong when two
  of the caller's words occur within three words of each other. Ranking
  uses `ts_rank` with the bm25 column weights. Postgres stopwords are
  ignored rather than reported as unmatched. No `pg_trgm`: the original had
  no fuzzy matching.
- Different: crawling is generic (any sitemap, robots.txt, paced, bounded)
  instead of BigCommerce's `xmlsitemap.php?type=products&page=N` (a sitemap
  index there is followed the same way). JSON-LD `@graph`, a list of
  `@type`s, AggregateOffer `lowPrice` and `productID`/`mpn` when there is no
  `sku` are also understood. Prices are exact decimals, not floats.
- Not ported: `/transfer_destination` and `TRANSFER_DESTINATION`. Transfers
  are done by the platform's transfer tool with its own destination and
  wait message; only the no-match transfer offer is configurable here.
- Not ported: `/health` with a product count (the connection's sync status
  carries it).

## Auth families and reuse

Providers declare an `auth_family` (`google-calendar` and `google-sheets`
are `google`).

- **OAuth clients belong to the family.** A client saved for Calendar
  (`POST /internal/provider-apps`) is listed with `provider: "google"` and
  starts Sheets flows too (migration 0005 moved existing clients). Each
  provider still has its own redirect URI (`/oauth/{provider}/callback`):
  add every one you use to the client.
- **Service accounts can be reused.** `POST /internal/connections` with
  `reuse_secret_from: <connection id>` (and no `secret`) copies the
  encrypted key of an active connection of the same org, family and auth
  mode server-side; the key never travels to the browser. Other orgs'
  connections are 404, revoked or errored ones 409, other families or
  auth modes 422.
- **OAuth sign-ins are not shared.** Each provider keeps its own connection
  and refresh token, so revoking or reconnecting one never breaks another.
  To keep it to one click, `oauth/start` accepts `login_hint` (the UI
  passes the account an existing family connection uses) and Google's
  `include_granted_scopes=true` makes the consent screen ask only for the
  new scopes.

## OAuth2 (bring-your-own client)

A workspace connects its own Google account with its own OAuth client; the
platform-wide Fallcha client comes later. One-time setup in the workspace's
Google Cloud project:

1. Enable the **Google Calendar API** and/or the **Google Sheets API**.
2. Configure the OAuth consent screen (an *Internal* app needs no Google
   review; an *External* app in testing works for its listed test users,
   whose refresh tokens expire after 7 days).
3. Create an OAuth client of type **Web application** and add the
   **authorized redirect URI** of each Google integration you use (exactly;
   `oauth/start` and the catalog also return it). One client serves them all:

   ```
   {TOOLS_PUBLIC_BASE_URL}/oauth/google-calendar/callback
   {TOOLS_PUBLIC_BASE_URL}/oauth/google-sheets/callback
   ```

The flow, driven by the Fallcha API (`/api/v1/integrations/...`):

| Step | Tools service |
|---|---|
| Save the client | `POST /internal/provider-apps {provider, client_id, client_secret}` (stored under the provider's auth family; secret encrypted, never returned; `GET` lists, `DELETE` removes one unless a live connection uses it) |
| Start | `POST /internal/oauth/start {provider, provider_app_id, optional_scopes?, login_hint?}` returns `authorization_url`, `redirect_uri` and a `browser_nonce`, which the Fallcha API returns to the starting user only; the UI keeps it in that tab's `sessionStorage` |
| Consent | The browser goes to Google, then to `/oauth/{provider}/callback` |
| Callback | Creates a **pending** `oauth2` connection, then redirects to `TOOLS_UI_RETURN_URL?integration_result=success&connection_id=...&provider=...`, or `...=error&reason=<code>` |
| Confirm + activate | `POST /api/v1/integrations/connections/{id}/activate` forwards the `browser_nonce` from its body to `POST /internal/connections/{id}/confirm`, which makes it active only for the same org, the user who started the flow, and a matching nonce; the API then issues a key and installs the MCP tool |

A pending connection is not listed, cannot get a key and cannot be used.
If nobody confirms it within 10 minutes it is revoked and its tokens are
wiped. This stops consent phishing (a start link sent to someone
else): the callback, and so the new connection's id, lands in the victim's
browser, which has neither the sender's session nor the sender's nonce, so
it cannot confirm the connection; and the sender, who has both, never
learns the id, since pending connections are not listed.

Error `reason` codes: `invalid_state`, `expired_state`, `access_denied`,
`authorization_failed`, `client_missing`, `token_exchange_failed`,
`no_refresh_token`, `scopes_missing`, `internal_error`.

**Scopes.** Google Calendar requests `calendar.events` (book, read, cancel
events) and `calendar.readonly` (free/busy, calendar name); never full
`calendar`. Google Sheets requests `spreadsheets`. Both add `openid email`
to label the connection with the account's address, and declare no
optional scopes (the `optional_scopes` mechanism stays for providers that
need it). If the user unticks a required scope on the consent screen, the
callback fails with `scopes_missing`. A new OAuth Calendar connection's
`calendar_id` defaults to `primary`; a new Sheets connection has no
spreadsheet until one is set with `PATCH /internal/connections/{id}`.

**Security.** The state is 256 random bits, stored only as a SHA-256 hash,
bound to org, user, provider and client, valid for 10 minutes and consumed
by a single `DELETE ... RETURNING` (a replayed or concurrent second use
fails). PKCE (S256) protects the code; the verifier is stored encrypted.
The client secret, refresh token and access token are encrypted at rest and
never logged or returned. The callback only ever redirects to the
configured `TOOLS_UI_RETURN_URL`, with fixed reason codes, `Cache-Control:
no-store` and `Referrer-Policy: no-referrer`. The uvicorn access log shows
`/oauth/...?<redacted>` instead of the code and state (a reverse proxy in
front must not log the query of that path either).

**Refresh.** Tokens are refreshed lazily when they expire within 5 minutes.
In one process, concurrent calls share one refresh; across replicas, the
refresh runs under `pg_advisory_xact_lock` plus a row lock (lock waits are
capped by `lock_timeout`) and re-reads the row once it holds them, so
exactly one request goes to Google. The refresh runs in a shielded task: a
tool call that hits its deadline gives up waiting, but the refresh still
finishes and is stored (with any rotated refresh token). A successful
refresh clears an earlier `error` status. If Google answers `invalid_grant`
(access revoked, password changed, testing-mode token expired), the
connection becomes `status=error`, `error_code=grant_revoked`,
`last_error="Google access was revoked or expired; reconnect"`, and its
tokens are dropped; `invalid_client` sets `error_code=client_rejected`.
With an `error_code` set, tools return the message without calling Google
again. Reconnecting creates a new connection.

## Add a provider

1. Create `fallcha_tools/providers/<name>/` with a class that satisfies the
   `Provider` protocol in `fallcha_tools/core/provider.py`: `id`, `title`,
   `description`, `icon`, `auth_family`, `auth_modes`, `scopes`, `config_model`, `oauth`
   (an `OAuthSpec` if `auth_modes` includes `oauth2`, else `None`),
   `validate_secret()`, `register_tools()`, `test_connection()` and
   `rest_router()` (return `None` for no REST routes). OAuth2 tools get
   tokens from `await ctx.oauth.access_token()`.
2. In `register_tools(mcp, ctx_factory)`, declare tools with `@mcp.tool`.
   Inside each tool, `ctx = await ctx_factory()` gives the caller's
   `ConnectionContext`: org, connection, decrypted secret, access token and
   a shared `httpx.AsyncClient`, plus the connection's validated `config`
   and the service database (`ctx.db`; filter every query on org and
   connection). Give each tool a short `title` (the catalog shows it to
   people; the docstring is for the agent).
3. Optional: implement `sync_item_label` and `run_sync()` (see
   `SyncableProvider`) to import data in the background; the catalog then
   lists the `sync` capability. Fetch workspace-supplied URLs only through
   `fallcha_tools.core.netguard`.
4. Add an instance to `build_registry()` in `fallcha_tools/providers/__init__.py`.

The app mounts it at `/mcp/<id>` and lists it in `GET /internal/catalog`.
See `tests/echo_provider.py` for a minimal example,
`fallcha_tools/providers/google_sheets/` for a Google one (shared plumbing
in `providers/google_common/`) and `providers/website_catalogue/` for a
syncing one.
