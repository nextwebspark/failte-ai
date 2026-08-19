# Tool catalog — architecture, database, Java service, and UI

> **Status: design of record.** Companion to
> [`app-doc/tenancy-auth-roadmap.md`](./tenancy-auth-roadmap.md), which covers tenancy, RBAC and passwordless
> auth. This document depends on that one only for the Java service existing, and for vendor-scoped visibility
> in the final phase. [`saas/docs/FORK.md`](../saas/docs/FORK.md) remains binding on where code may live.

## The problem

Creating one working HTTP tool today costs roughly **26–28 discrete inputs across 2 pages, 3 tabs, 2 modals
and 2 API round trips** — and the user must already know the target API's method, path, auth scheme and body
shape.

The flow is worse than the count suggests. The create dialog collects three fields, then calls
`createHttpApiDefinition()`, which returns an **empty husk**:

```ts
// ui/src/app/tools/config.tsx
createHttpApiDefinition()  →  { schema_version: 1, type: "http_api", config: { method: "POST", url: "" } }
```

The tool is persisted in a non-functional state and the user is redirected to a second page to finish it. Name
and description are collected **twice** — once in the dialog, again in the Settings tab.

## The goal

A curated library where a user picks **"Google Calendar — Book Slot"**, connects their Google account, answers
one question, and has a working tool.

**Target: 2 clicks and 1 input.**

## What does not change

**Tool calling at runtime is untouched.** The catalog is an authoring-time concern. Specifically unchanged:

- [api/services/workflow/tools/custom_tool.py](../api/services/workflow/tools/custom_tool.py) — `execute_http_tool`
- [api/services/pipecat/pipecat_engine_custom_tools.py](../api/services/pipecat/pipecat_engine_custom_tools.py) — handler registration and dispatch
- [api/utils/credential_auth.py](../api/utils/credential_auth.py) — `build_auth_header`
- [api/schemas/tool.py](../api/schemas/tool.py) — the `ToolDefinition` discriminated union
- The `ToolCategory` enum, and therefore no Alembic enum migration

§3 explains how OAuth is delivered without touching any of them.

---

## 1. What already exists

A surprising amount of the required machinery is already in the tree, and most of it is unused.

| Thing | State | Use |
|---|---|---|
| `IntegrationModel` — `provider`, `connection_details` JSON, org-scoped | **Dead code.** Zero callers outside `api/db/`; no route, service, task or test touches it | **Supersede it.** No expiry columns, no encryption, no unique constraint, no `updated_at` |
| `IntegrationPackageSpec.routers` → `all_routers()` → auto-mounted at [api/routes/main.py:68](../api/routes/main.py#L68) | Built and wired; **no package has ever used it** | A free seam for OAuth callbacks in Python, needing zero edits to `main.py`, if we ever want them there |
| `McpToolConfig.discovered_tools` + `populate_discovered_tools()` + `POST /{uuid}/mcp/refresh` | Working | The precedent for server-populated tool definitions, best-effort population, and explicit refresh |
| `WorkflowTemplates` — no `organization_id` column at all | Working (its UI card, `TemplateCard.tsx`, is orphaned) | The precedent for a global, org-less catalog table |
| `preset_parameters` + `value_template` + `{{initial_context.*}}` / `{{gathered_context.*}}` | Working | Reuse verbatim. Catalog specs emit these directly |
| `create_tool_for_user(request, user, *, source="api")` | Working | The install target. `source` is analytics-only, so `"catalog"` is the idiomatic marker |
| `VoiceSelectorModal` — facets, 300 ms debounced search, scrollable body, explicit commit, manual-entry escape hatch | Working | The structural model for the catalog browser |
| `AddNodePanel` — icon square + title + wrapped description + disabled-with-reason | Working | The row grammar for a catalog entry |

### The finding that simplifies everything

`ToolCategory.INTEGRATION` already exists in the Postgres enum. Its comment reads *"Third-party integrations
(future: Google Calendar, Salesforce, etc.)"*. But there is no `IntegrationToolDefinition` in the
`ToolDefinition` union, and `CreateToolRequest` enforces `category == definition.type` — so a tool with
`category="integration"` is **uncreatable today**.

**We should not add one.**

A catalog-installed Google Calendar tool *is* an `http_api` tool: `POST` to
`https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events`, a bearer credential, pre-filled
parameters. The catalog's job is to author a complete `HttpApiConfig` — not to invent a new runtime shape.

The obvious instinct is to add an `integration` category. It would buy nothing and cost a new definition
variant that every validator, every generated SDK, the MCP authoring surface, the TS validator, and all three
LLM vendor adapters would have to learn.

---

## 2. Architecture at a glance

```
┌─────────────────────────────┐         ┌──────────────────────────────┐
│  Java  (failte_catalog)     │         │  Python  (public)            │
│                             │         │                              │
│  spec        — the library  │         │  tools               ← install│
│  oauth_provider             │         │  external_credentials ← rotate│
│  connection  — per org      │         │                              │
│  install     — spec ↔ tool  │         │  create_tool_for_user(...)   │
└─────────────────────────────┘         └──────────────────────────────┘
        │                                          ▲
        │  POST /api/v1/tools  (install)           │
        │  PUT  /internal/credentials/{u}/rotate   │
        └──────────────────────────────────────────┘
                    authoring time only

live call ──→ execute_http_tool ──→ build_auth_header ──→ Google
                    (Java is not in this path)
```

**Java owns the library. Python owns the instance.** Java authors a complete `definition` JSON and hands it to
Python's existing `POST /api/v1/tools`. Python's Pydantic union stays the single source of truth for what a
valid tool is — no validation logic is duplicated in Java.

---

## 3. OAuth without touching the live call path

This is the load-bearing decision in the whole design.

### The constraint

`ExternalCredentialModel` supports five static header types, and `build_auth_header` is **synchronous**:

```python
# api/utils/credential_auth.py
def build_auth_header(credential: "ExternalCredentialModel") -> Dict[str, str]:
    if cred_type == "bearer_token":
        token = cred_data.get("token", "")
        return {"Authorization": f"Bearer {token}"}
```

It structurally cannot refresh a token or write one back — every call site invokes it after an
already-completed DB fetch, synchronously, inside the live call. Making it async would reach into
`custom_tool.py`, `mcp_tool_session.py`, `webhook_delivery.py` and `pre_call_fetch.py`.

### The resolution

Notice what that function returns for `bearer_token`: `Authorization: Bearer <token>`. **That is exactly what
the Google Calendar API expects.** So an OAuth connection can be surfaced to Python as an ordinary
`bearer_token` credential whose value Java keeps fresh.

```
Java scheduled job, at 50% of token TTL
  → refresh against Google's token endpoint
  → PUT /internal/credentials/{uuid}/rotate     (X-Secret-Key, the MPS client pattern)
      → Python writes credential_data = {"token": "<fresh access token>"}

live call → execute_http_tool → build_auth_header(credential) → Authorization: Bearer <token> → Google
```

**Zero changes to `build_auth_header`, zero to `custom_tool.py`, zero to the call path. Java is never in the
call path.** "Tool calling stays as it is" is literally true, not approximately true.

Rotation goes through an internal endpoint rather than a direct write because Java is read-only on Python's
tables — the same rule and the same `X-Secret-Key` shape as
[api/services/mps_service_key_client.py](../api/services/mps_service_key_client.py).

### The residual failure mode, stated honestly

A token can expire between refreshes. The result is a 401, which `execute_http_tool` returns to the LLM as a
structured error — the call does not crash, but the tool does not work. Two mitigations:

1. Refresh at **50% of TTL**, not at expiry. Google access tokens live ~1 hour, so a refresh every ~30 minutes
   leaves a wide margin for a failed job run.
2. An out-of-band refresh triggered by observed 401s on integration tools.

### Credential encryption becomes mandatory

`credential_data` is stored in **plaintext**. The comment at [api/db/models.py:999](../api/db/models.py#L999)
reads *"Encrypted credential data (JSON)"*; a repo-wide grep for `encrypt|decrypt|fernet|cryptography|kms|vault`
across `api/` returns **exactly one hit — that comment.** No encryption library, no `TypeDecorator`, no
transform on read or write.

Today the column holds API keys. Under this design it holds Google **refresh tokens**, which are long-lived
and grant standing access to a user's calendar and mail. Encryption at rest is therefore a hard prerequisite,
delivered as its own phase (C2) **before** any OAuth work lands. It also closes a pre-existing hole
independent of this feature.

---

## 4. Database

### 4.1 Java — `failte_catalog`, owned by Flyway

Alembic never sees this schema; Flyway never touches `public`.

**`spec`** — the library entry.

| Column | Notes |
|---|---|
| `spec_id` | Stable reverse-DNS id, e.g. `ai.failte.google.calendar.book_slot` |
| `version` | Semver. `(spec_id, version)` unique |
| `title`, `description` | User-facing |
| `icon`, `icon_color` | Lucide icon name + hex — the existing `CreateToolRequest` fields |
| `provider_id` | Nullable FK → `oauth_provider`. Null means an API-key or unauthenticated spec |
| `definition_template` | JSONB — a complete `HttpApiConfig` with `{{input.*}}` placeholders |
| `inputs` | JSONB — see §4.3 |
| `status` | `draft` / `published` / `deprecated` |
| `visibility` | `global` / `vendor` |
| `owner_org_id` | Nullable. Set only for vendor-published specs |
| `docs_url` | Nullable — feeds the existing per-tool "Docs" link pattern |

`visibility` and `owner_org_id` ship in v1 **unused**, so vendor publishing in C7 needs no migration.

**`oauth_provider`** — `provider_id` (`google`), authorize URL, token URL, default scopes, client id, client
secret (encrypted), and whether the provider supports incremental authorisation.

**`connection`** — a per-organization link to a third-party account.

| Column | Notes |
|---|---|
| `organization_id` | Scoped to the customer org |
| `provider_id` | FK → `oauth_provider` |
| `display_label` | The connected account's email, so `/connections` can show "connected as alice@acme.com" |
| `refresh_token_enc`, `access_token_enc` | Encrypted |
| `expires_at` | Drives the refresh scheduler |
| `scopes_granted` | What the user actually consented to, which may be less than requested |
| `credential_uuid` | The Python `external_credentials` row this connection rotates |
| `status` | `active` / `revoked` / `error` |

**`install`** — the link that makes upgrades possible.

`spec_id`, `spec_version`, `organization_id`, `tool_uuid` (Python's), `connection_id`, `inputs_answered`
JSONB, `installed_at`.

Recording the source version and the answers means a new spec version can be **diffed and re-rendered** rather
than guessed at, and a user's hand-edits can be detected before an upgrade clobbers them.

### 4.2 Python — one column changes

**No new tables.** The only schema change is encrypting `external_credentials.credential_data`, via a
SQLAlchemy `TypeDecorator` so call sites are unchanged, plus a batched backfill of existing rows and a
correction to the false comment.

`tools` is untouched: `organization_id` stays `NOT NULL`, every query stays org-scoped. Catalog specs are
global; installed **tools** remain strictly per-org, which is what keeps the existing tenant isolation intact.

### 4.3 The `definition_template` + `inputs` mechanism

A spec declares what the user must supply:

```
inputs: [ { key, label, type, help, required, source } ]
source ∈ literal | connection | picker
```

| Source | Meaning |
|---|---|
| `literal` | The user types it (a Slack channel name, a sheet range) |
| `connection` | Resolved from the OAuth connection; never shown as a field |
| `picker` | The UI asks Java for options; Java calls the provider using the connection |

**`picker` is what makes configuration feel fast.** Instead of hunting for a calendar ID in Google's settings,
the user chooses "Work Calendar" from a list.

Install renders `definition_template` with the answers plus the connection's `credential_uuid`, then POSTs the
result to Python.

---

## 5. Java Spring application changes

All new code, in the top-level `java/` directory — zero merge cost per FORK.md.

```
java/src/main/java/ai/failte/catalog/
├── spec/          SpecEntity, SpecRepository, SpecService, SpecController
│                  publish / deprecate / list (visibility-filtered)
├── render/        TemplateRenderer      — {{input.*}} substitution into definition_template
│                  DefinitionBuilder     — produces the CreateToolRequest body
├── install/       InstallService        — render → POST to Python → record install
│                  InstallController, InstallEntity
├── oauth/         OAuthProviderRegistry — google, seeded from failte_catalog.oauth_provider
│                  AuthorizeController   — /catalog/oauth/{provider}/authorize  (PKCE, state)
│                  CallbackController    — /catalog/oauth/{provider}/callback
│                  TokenRefreshScheduler — @Scheduled, refreshes at 50% TTL
├── connection/    ConnectionEntity, ConnectionService, ConnectionController
│                  PickerService         — calls the provider for `picker` options
├── client/        DograhApiClient       — POST /api/v1/tools, PUT /internal/credentials/{u}/rotate
└── crypto/        Envelope encryption for refresh tokens and provider secrets

java/src/main/resources/db/migration/   Flyway, failte_catalog only
java/src/main/resources/catalog/        Seed spec YAML, loaded on startup
```

**Spring dependencies:** `spring-boot-starter-web`, `-data-jpa`, `-oauth2-client` (already present for Google
sign-in in the auth roadmap), `-validation`, `spring-boot-starter-quartz` or plain `@Scheduled` for refresh,
and Flyway.

Two notes on the refresh scheduler:

- It must be **idempotent and single-flight across instances**. Two Java replicas refreshing the same
  connection concurrently will race, and Google invalidates the previous refresh token on rotation for some
  grant types. Use a DB advisory lock or Quartz's clustered scheduler.
- A refresh failure marks the connection `error` and must surface on `/connections`. Otherwise the first
  symptom of a user revoking access is a failing live call.

---

## 6. UI changes

Four surfaces, all built from patterns already in the codebase.

### 6.1 Catalog browser

Entry point: a "Browse catalog" action beside the existing "Create Tool" button on
[ui/src/app/tools/page.tsx](../ui/src/app/tools/page.tsx).

Structure copied from `VoiceSelectorModal`, which is the closest existing precedent:

```tsx
<Dialog>  className="flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl"
  ├─ filter row      Select facets (provider, category) + debounced search Input (300 ms)
  ├─ scrollable body min-h-[260px] flex-1 overflow-auto
  │    └─ rows       AddNodePanel grammar: icon square + title + wrapped description
  └─ footer          explicit commit — "Install", not select-on-click
```

Row grammar from `AddNodePanel`, including its **disabled-with-reason** treatment — a spec needing a
connection the org does not yet have is not hidden, it is shown with an explanatory tooltip.

`cmdk` is not a dependency and there is no `command.tsx`, so search is a debounced `Input` as everywhere else
in the app — not a command palette.

### 6.2 Install sheet

Two steps, and the second is often a single field.

1. **Connect** — if the spec has a `provider_id` and the org has no active connection, a Connect button opens
   the OAuth flow in a popup. Existing connections are offered for reuse.
2. **Configure** — render only the `inputs` with `source: literal | picker`. Everything else is already in the
   template.

For **Google Calendar — Book Slot**, step 2 is one `picker`.

Include the manual-entry escape hatch that `VoiceSelectorModal` already provides via `allowManualInput` — a
`picker` that cannot reach the provider must degrade to a text field, not a dead end.

### 6.3 In-canvas tab

[ui/src/components/flow/ToolSelector.tsx](../ui/src/components/flow/ToolSelector.tsx) has a two-tab `TabsList`
at lines 169–176 (`http`, `mcp`). Add a third, `catalog`.

This matters because today the empty state and the footer both link to `/tools` with `target="_blank"` —
building an agent and needing a tool **drops the user out of the workflow editor into a new browser tab**.

### 6.4 `/connections` page

There is **no credentials page at all** today. `find ui/src -iname "*credential*"` returns two files, both
under `components/http/`, and the only creation path is a dialog nested inside a tool form.

Connections need a home: list, connected-as label, granted scopes, which tools depend on each one, reconnect,
and revoke. Built on the card-grid pattern already used in `app/workflow/page.tsx`.

Note the API gap this exposes: `CredentialResponse` deliberately never returns `credential_data`, so a UI
cannot show connection metadata without new fields. Connection display data comes from Java, not from
Python's credential row.

---

## 7. Worked example — Google Calendar, Book Slot

### The spec

```yaml
spec_id: ai.failte.google.calendar.book_slot
version: 1.0.0
title: Google Calendar — Book Slot
description: Book an event on a Google Calendar during a call.
icon: calendar
provider_id: google
inputs:
  - key: calendar_id
    label: Which calendar?
    source: picker
    picker_endpoint: google.calendarList
    required: true
definition_template:
  schema_version: 1
  type: http_api
  config:
    method: POST
    url: https://www.googleapis.com/calendar/v3/calendars/{{input.calendar_id}}/events
    credential_uuid: "{{connection.credential_uuid}}"
    timeout_ms: 5000
    customMessage: "Let me get that booked for you."
    parameters:
      - { name: summary,    type: string, description: "Title of the event",       required: true }
      - { name: start_time, type: string, description: "ISO 8601 start",           required: true }
      - { name: end_time,   type: string, description: "ISO 8601 end",             required: true }
    preset_parameters:
      - { name: attendee_email, type: string, value_template: "{{gathered_context.email}}", required: false }
    body_template:
      summary: "{{summary}}"
      start:   { dateTime: "{{start_time}}" }
      end:     { dateTime: "{{end_time}}" }
      attendees: [ { email: "{{attendee_email}}" } ]
```

Note `preset_parameters` pulling the attendee's address out of the live call's gathered context — that
mechanism already works and needs no changes.

### What the user does

1. Tools → Browse catalog → "Google Calendar — Book Slot"
2. **Connect Google** → consent → back
3. **Which calendar?** → pick "Work Calendar"
4. Install

**One input.** Against 26–28 today.

### What happens end to end

```
install  → Java renders definition_template with {calendar_id, credential_uuid}
         → POST /api/v1/tools  → create_tool_for_user(source="catalog") → tools row
         → record failte_catalog.install

attach   → workflow editor → node → Tools → the new tool

live call→ LLM emits book_slot(summary, start_time, end_time)
         → execute_http_tool
         → fetch credential by uuid  → build_auth_header → Authorization: Bearer <token>
         → POST to Google → 200 → result to LLM

meanwhile→ Java refreshes the token every ~30 min via /internal/credentials/{uuid}/rotate
```

**At no point in the live call is Java contacted.**

---

## 8. Delivery phases

| # | Phase | Content | Exit criterion |
|---|---|---|---|
| **C0** | Documentation | This document | Reviewed |
| **C1** | Catalog loop, no OAuth | `spec` + `install` tables, read API, 3 API-key specs (Slack webhook, SendGrid, generic REST), browser + install sheet, POST through to Python | A user installs a working Slack tool in **under 4 inputs** and it fires on a real call |
| **C2** | Credential encryption | Envelope encryption on `credential_data`, key management, backfill, correct the false comment | Existing credentials still authenticate; ciphertext confirmed at rest in `psql` |
| **C3** | Generic OAuth2 + Google | `oauth_provider` + `connection`, authorize/callback with PKCE, refresh scheduler, rotate endpoint | A Google connection survives token expiry with no user action, proven by fast-forwarding TTL |
| **C4** | Google specs + `picker` | Calendar, Sheets, Gmail specs; the `picker` input source | **Book Slot installs with one input and books a real event from a real call** |
| **C5** | Reach | Third `ToolSelector` tab; `/connections` page | A tool is installed without leaving the workflow canvas |
| **C6** | Versioning | Semver diffing, upgrade prompts driven by `install`, deprecation | A spec upgrade is offered, previewed, and applied without breaking a live agent |
| **C7** | Vendor publishing | Flip on `visibility` + `owner_org_id`; approve flow | A vendor publishes a spec visible only to their own customers |

**Ordering that matters: C2 before C3.** Storing Google refresh tokens in plaintext is not acceptable even
briefly. C1 deliberately ships API-key specs so the entire install loop is proven before OAuth is introduced.

---

## 9. Files

**New — Java** (`java/`, zero merge cost): the packages in §5, Flyway migrations for `failte_catalog`, seed
spec YAML.

**New — Python**: `api/saas/routes/internal_credentials.py` (the rotate endpoint) and `api/saas/crypto/`
(envelope encryption).

**New — UI**: `ui/src/saas/catalog/` (browser, install sheet, connect button) and `ui/src/app/connections/`.

**Upstream files touched:**

| File | Change |
|---|---|
| [api/db/models.py](../api/db/models.py) | `credential_data` → encrypted `TypeDecorator`; fix the false comment |
| [api/db/webhook_credential_client.py](../api/db/webhook_credential_client.py) | encrypt on write, decrypt on read |
| [api/routes/main.py](../api/routes/main.py) | one `include_router` appended |
| [ui/src/app/tools/page.tsx](../ui/src/app/tools/page.tsx) | a "Browse catalog" entry point |
| [ui/src/components/flow/ToolSelector.tsx](../ui/src/components/flow/ToolSelector.tsx) | a third tab at the `TabsList` on line 169 |

**Explicitly not touched:** `api/schemas/tool.py`, `api/services/workflow/tools/custom_tool.py`,
`api/services/pipecat/*`, `api/utils/credential_auth.py`, and the `ToolCategory` enum.

---

## 10. Risks and open questions

- **Google OAuth consent-screen verification.** Calendar and Gmail scopes are "sensitive" or "restricted";
  verification can take weeks and may require a third-party security assessment. This gates C4's *public
  availability*, not its development — **start the submission during C3.**
- **`picker` puts a third-party call inside an authoring request.** Needs a timeout, a cached result, and the
  manual-entry escape hatch. A slow Google response must not hang the install sheet.
- **Spec-to-runtime drift.** A spec is authored against an API that can change under us. Per-spec conformance
  fixtures, run in CI, are the only honest defence.
- **Upgrade semantics.** If a user hand-edits an installed tool, a later spec upgrade must not silently
  clobber it. `install` records the source version and answers; the upgrade path has to diff and ask.
- **Token revocation.** A user revoking access in their Google account leaves a dead connection. Detect on
  refresh failure, mark it `error`, surface on `/connections`.
- **Refresh races across Java replicas.** Google invalidates the prior refresh token on rotation for some
  grant types, so concurrent refreshes can break a working connection. Needs a DB advisory lock or a clustered
  scheduler.
- **Encryption key management.** Envelope encryption needs a KMS or an operator-managed key with a rotation
  story. Where that key lives is an infrastructure decision to record, not assume.
- **Rate limits.** Google Calendar has per-project quotas. Many orgs installing the same spec share our OAuth
  client, so quota is a shared resource — monitor before it becomes a support incident.
