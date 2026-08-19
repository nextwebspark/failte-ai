# Tenancy, RBAC, passwordless auth, and the Java control plane

> **Status: design of record.** Supersedes the hierarchy model in [`saas/docs/RBAC.md`](../saas/docs/RBAC.md)
> and closes the open decision in [`saas/docs/AUTH-PROVIDER.md`](../saas/docs/AUTH-PROVIDER.md).
> [`saas/docs/FORK.md`](../saas/docs/FORK.md) remains binding on where code may live.
>
> **Partially superseded by [`tenancy-stack-auth.md`](./tenancy-stack-auth.md).** That document replaces the
> identity half of this one: the Spring Authorization Server decision, and Phases 1–4 (Java skeleton, email
> delivery, email OTP, Google sign-in), which self-hosted Stack Auth provides natively. Everything else here
> stands and is carried over intact — the hierarchy schema (§1), scope resolution (§4), the permission model
> (§5), the RLS design (§6), the tool-standard catalog (§7) and the Java `http_api` executor (§8). Where the two
> documents disagree on identity, the newer one wins; where they disagree on nothing else, they do not disagree.

## Context

Private fork of `dograh-hq/dograh` being turned into a multi-tenant SaaS. Three needs drove this design:

1. **A three-level tenant tree**, admin/member at each level:

```
Platform (us)            admin · member
└── Vendor (reseller)    admin · member
    └── Customer (the end company we build agents for)   admin · member
```

Each level sees everything in its subtree; what it can *change* depends on admin vs member.

2. **A standardised tool-call catalog**, built in **Java/Spring Boot**, deployed beside the Python server,
also owning identity and `http_api` tool execution.

3. **Passwordless sign-in** — email + a code sent to the email, plus Google sign-up/sign-in.

### What already exists

Upstream is genuinely multi-tenant: `organizations`, `organization_users` M2M,
`users.selected_organization_id`, `organization_id` FKs on ~20 tables. Missing exactly two things — **roles**
(no `role` column anywhere; only boolean `users.is_superuser`) and **hierarchy** (orgs are flat).

**No tool catalog.** `ToolModel.organization_id` is `NOT NULL`, so no global or shared tool can exist —
sharing means POSTing the same tool N times. Parameters are a flat
`ToolParameter{name, type, description, required}` list: no nesting, enums, `format`, or bounds; `object`
expands to `{"additionalProperties": true}`, `array` to `{"items": {}}`.

**No email infrastructure at all.** Verified by grep across the repo: zero hits for
`smtplib|aiosmtplib|MIMEText|sendgrid|resend|mailgun|postmark|SESClient`. No mail library in
`api/requirements.txt` (only `email-validator`, which is just the `EmailStr` backend), no `SMTP_*`/`MAIL_*`
env in `constants.py`, compose or Helm, no template engine, no `api/templates/`. `arq` exists, so async sends
have a home, but everything else is greenfield.

**No OAuth code of our own.** No `authlib`/`oauthlib`/`google-auth` on the backend, no `next-auth` in the UI.
Social login today is entirely inside `@stackframe/stack`. Every `google` hit in the repo is vendored pipecat
Gemini/Vertex *model* integration, not sign-in.

### Decisions taken

| Decision | Choice |
|---|---|
| Identity provider | **Spring Authorization Server — our own IdP in Java.** Supersedes the Zitadel/Keycloak evaluation |
| Sign-in methods | **Email OTP code + Google OAuth. No passwords, ever** |
| Isolation | Application-level scoping **and** Postgres RLS |
| Cross-vendor membership | **Forbidden**, enforced structurally in the DB |
| Java owns | Identity, tenancy/RBAC, the tool-standard catalog, `http_api` execution |
| Java DB access | **Writes only its own schema; read-only on Python's tables** |

**Going passwordless materially shrinks the own-IdP cost.** Gone: password storage and rotation, password
reset, credential stuffing, password-strength policy, breach-list checks. What remains is listed honestly
in §2.

---

## The collision in the decisions, and the resolution

"Java owns auth and tenancy" and "Java is read-only on shared tables" cannot both hold literally — creating an
org or changing a role means writing `organizations` and `organization_users`, Python's tables.

**Resolution: the hierarchy does not live in Python's tables at all.**

| Table | Schema | Written by |
|---|---|---|
| `public.users`, `public.organizations` | Python (upstream, **unchanged**) | Python only |
| `failte_auth.org_node` — `organization_id` PK/FK→`public.organizations.id`, `org_type`, `parent_organization_id`, `tenant_root_id`, `name`, `slug`, `branding` | Java | Java only |
| `failte_auth.membership` — `user_id` FK→`public.users.id`, `organization_id`, `role`, `tenant_root_id` | Java | Java only |
| `failte_auth.identity`, `identity_credential`, `otp_challenge`, `invitation`, `audit_log`, `catalog_*` | Java | Java only |
| everything org-scoped (workflows, tools, campaigns…) | Python | Python only |

Cross-schema foreign keys are legal in one database, so Java's tables reference Python's rows without writing
them. **Java gets one write exception, and it is not a write** — a service-to-service
`POST /internal/provisioning/organization` on the Python API creates the shell `public.organizations` /
`public.users` rows, authenticated like the existing MPS client
([api/services/mps_service_key_client.py](../api/services/mps_service_key_client.py), `X-Secret-Key`).

**This is strictly better than putting the hierarchy on upstream's models.** `api/db/models.py` delta drops
from **~60 lines to ~10** — only the five `organization_id` columns on transitively-scoped tables remain. The
hierarchy adds *zero* lines to `UserModel`, `OrganizationModel`, or the association table. Per
[FORK.md](../saas/docs/FORK.md) every line in an upstream file is a conflict paid on every sync. And one
source of truth for the tree means no projection, no staleness window, no chance of RLS computing the wrong
boundary from a stale `tenant_root_id`.

---

# Part A — Architecture

## 1. Hierarchy schema — declarative, no triggers

```sql
CREATE TYPE failte_auth.org_type AS ENUM ('platform', 'vendor', 'customer');
CREATE TYPE failte_auth.org_role AS ENUM ('admin', 'member');
```

Six roles from two enums: a role is the pair `(org_node.org_type, membership.role)`. This keeps the enum
stable if a fourth tenant level ever appears.

Depth is capped at three **by referential integrity, not policy** — a CHECK pins `parent_org_type` from
`org_type`, and a composite FK `(parent_organization_id, parent_org_type) → org_node (organization_id,
org_type)` forces a customer's parent to be a vendor and a vendor's parent to be the platform. A fourth level
is not forbidden by convention; it is unrepresentable.

### The single-vendor constraint — two foreign keys, no trigger

`tenant_root_id` is never NULL (platform and vendor nodes are their own root):

```
fk_membership_org_root   (organization_id, tenant_root_id) → org_node (organization_id, tenant_root_id)
fk_membership_user_root  (user_id,         tenant_root_id) → identity (user_id,        tenant_root_id)
```

A user's `tenant_root_id` is a single scalar, so every membership they hold must resolve to the same root.
**No INSERT satisfies both FKs across two vendors.** No trigger, no application check.

"Platform is its own root" is load-bearing: with a NULL root, both FKs go unenforced under `MATCH SIMPLE` and
a platform user could quietly acquire a vendor membership.

### No closure table, no materialized path, no recursive CTE

`tenant_root_id` — needed anyway for the constraint — collapses every subtree query to equality:

| Actor scope | Predicate | Cost |
|---|---|---|
| platform | *(unrestricted)* | — |
| vendor, acting in org `V` | `tenant_root_id = V` | one index scan |
| customer, acting in org `C` | `organization_id = C` | PK lookup |

That is the payoff of a bounded-depth tree: the denormalization that enforces the constraint also serves the
query. If a fourth *tenant* level is ever introduced, the right move is `ltree` on a `path` column with a GiST
index — not a closure table, and not a recursive CTE in the request path. Do not build it now.

## 2. Passwordless identity

### 2.0 What Spring Authorization Server is, and is not

It is an OAuth2/OIDC **protocol** framework: authorization endpoint, token endpoint, JWKS, introspection,
client registration. It ships **no** user management, **no** login UI, **no** email, **no** account linking,
**no** MFA, **no** SAML. Going passwordless removes the password half of that burden. What we still build and
own:

- OTP issue / verify / rate-limit / lockout
- **Transactional email delivery and deliverability** — see §2.4, this is the real dependency
- Google federation, and the account-linking rule in §2.3
- Session and refresh token lifecycle, and revocation
- Invitation acceptance
- Enterprise SSO/SAML, later

This is recorded as an accepted cost with an explicit list, so it is planned rather than discovered.

### 2.1 Identity model (`failte_auth`)

```
identity            (id uuid pk, tenant_root_id, email citext, email_verified_at, status, created_at)
identity_credential (identity_id, kind ∈ {google, email_otp}, subject, UNIQUE(kind, subject))
otp_challenge       (id uuid pk, email citext, code_hash, expires_at, attempts, consumed_at, created_ip)
```

No password column exists. `identity_credential.subject` is Google's `sub` for Google and the email for OTP.
**Google's `sub`, never the email, is the stable key** — a Google account's email can change.

### 2.2 Email OTP flow

```
POST /auth/otp/start   {email}                → 200 {challenge_id}      (always 200)
POST /auth/otp/verify  {challenge_id, code}   → 200 {token, user}
```

Rules, each for a stated reason:

- **`start` always returns 200**, whether or not the email is known — otherwise the endpoint is a user
  enumeration oracle.
- **The code is bound to `challenge_id`, not to the email.** Binding to email alone lets an attacker who knows
  the address open many concurrent challenges and brute-force across them, multiplying the attempt budget.
- **6 digits, max 5 attempts, 10-minute expiry, single use.** On the 5th failure the challenge is burned, not
  merely counted.
- **Constant-time comparison**, hashed at rest — an OTP is a credential for its lifetime.
- **Rate limits on both axes**: per email and per source IP, since either alone is trivially evaded.
- Sign-up and sign-in are the *same* flow. `ENABLE_SIGNUP=false` makes `verify` reject unknown emails,
  preserving the existing flag's meaning ([constants.py](../api/constants.py)).

### 2.3 Google — one rule matters more than the rest

Authorization code + PKCE. Java acts as an OAuth2 *client* to Google (`spring-boot-starter-oauth2-client`)
while being the authorization *server* to our own apps.

> **Link a Google identity to an existing email identity only when Google's ID token asserts
> `email_verified: true`.**

Without that check, anyone who can get Google to issue a token for an unverified address they typed can be
linked into someone else's account. This is the highest-severity rule in the auth design. Also validate `aud`,
`iss` and `nonce`, and verify `state` on the callback.

### 2.4 Email delivery is a hard dependency, not a detail

An OTP mail that lands in spam is a **total login outage with no workaround** — there is no password to fall
back to. Deliverability is therefore a first-class requirement: a dedicated sending domain or subdomain,
SPF + DKIM + DMARC, bounce and complaint handling, a provider with a transactional (not marketing) reputation
pool, and monitoring on delivery latency — an OTP that arrives in four minutes is a failed login.

Send asynchronously through `arq`, but **fail the request loudly if enqueueing fails** rather than returning
200 on an email that will never be sent.

### 2.5 Tokens — and a latent trap in the existing code

Java issues the session JWT. Python validates it **locally against Java's JWKS** with cached keys; there is
deliberately no per-request Python→Java call, which would put a hard dependency on every hot path including
inbound telephony.

Claims: `sub` (Java identity uuid → `users.provider_id`), `email`, vendor org id, and **`typ`**.

> **`typ` is not optional.** Today `create_jwt_token` ([api/utils/auth.py](../api/utils/auth.py)) mints
> `{sub, email, exp, iat}` with **no purpose claim**. Introducing a second token kind without one means a
> session JWT would be accepted anywhere a challenge token is, and vice versa. Every token we mint carries
> `typ`, and every verifier asserts the expected value.

Cookie names `dograh_auth_token` / `dograh_auth_user` are **kept** — FORK.md rule 1 is never to rename wire
values, and these are duplicated across five files
([session/route.ts](../ui/src/app/api/auth/session/route.ts), `oss/route.ts`, `logout/route.ts`,
[lib/auth/server.ts](../ui/src/lib/auth/server.ts), [middleware.ts](../ui/src/middleware.ts)). The
token→cookie→interceptor chain is unchanged: backend returns `{token, user}` in the body → the form POSTs it
to `/api/auth/session` → two `httpOnly` cookies → `/api/auth/oss` reads them back → `tokenRef` →
`setupAuthInterceptor`.

## 3. How every API request gets validated

The most common worry about splitting identity into a second service is that each of the ~136 authenticated
endpoints now depends on that service being up. **It does not.** Python validates tokens locally, exactly as
it does today; the only change is the signature algorithm.

### Today, `local` mode

```
UI login  →  Python POST /auth/login  →  {token, user}     HS256, signed with OSS_JWT_SECRET
every request  →  interceptor adds  Authorization: Bearer <token>
Python get_user  →  _handle_oss_auth  →  decode_jwt_token()          ← local crypto, no network
                                      →  get_user_by_id(payload["sub"])
```

### With Java, `failte` mode

```
UI login  →  Java POST /auth/otp/verify  →  {token, user}   RS256, signed with Java's private key
every request  →  interceptor adds  Authorization: Bearer <token>    ← byte-for-byte identical
Python get_user  →  _handle_failte_auth  →  verify RS256 vs Java's PUBLIC key   ← local crypto, no network
                                         →  get_or_create_user_by_provider_id(payload["sub"])
```

**The only structural difference is a shared secret becoming a public key.** Java's public keys are fetched
once from its JWKS endpoint and cached in memory. Python makes **no per-request call to Java**.

This is not an optimisation, it is a availability requirement. The dependency counts:

| Dependency | Call sites |
|---|---|
| `Depends(get_user)` | 118 |
| `Depends(get_user_with_selected_organization)` | 15 |
| `Depends(get_user_ws)` | 1 |
| `Depends(get_superuser)` | 2 |

136 sites across 21 files. If validation required a hop to Java, every one becomes a distributed call and a
Java outage takes down the whole API — including live telephony, which authenticates over WebSocket. With
local JWKS validation, Java can be entirely down and existing sessions keep working; only new logins fail.

### The three auth paths, and what each needs

| Path | Change needed |
|---|---|
| **Header JWT** (the main path) | The new `failte` branch in `get_user`. Three lines |
| **`X-API-Key`** | **None.** API keys are Python-issued, stored in Python's `api_keys` table, validated by Python. Java is not involved at any point |
| **WebSocket** (`get_user_ws`) | **None.** It delegates to `get_user`, so it inherits the new branch for free — but verify explicitly, since telephony rides on it |

### What changes on the Python side

One new file, `api/saas/auth/depends_failte.py`, plus a three-line branch in `get_user` mirroring the shape of
the existing `local` branch so a merge conflict resolves obviously. **The 136 call sites change nothing** —
they take `user: UserModel = Depends(get_user)` and are indifferent to where the token came from. That
indifference is the whole reason the `AUTH_PROVIDER` seam is worth using rather than replacing.

### What changes on the JavaScript side

| Thing | Change |
|---|---|
| `setupAuthInterceptor` in [ui/src/lib/apiClient.ts](../ui/src/lib/apiClient.ts) | **none** — it calls `getAccessToken()` and does not know the provider |
| `AuthContextType` | **none** — it already abstracts `stack` and `local` behind `getAccessToken` / `redirectToLogin` / `logout` |
| Cookie names and the session round-trip | **none** — see §2.5 |
| `AuthProvider` union in [ui/src/lib/auth/types.ts](../ui/src/lib/auth/types.ts) | one line: add `'failte'` |
| `ui/src/saas/auth/FailteProviderWrapper.tsx` | new file, beside the existing two wrappers |
| OTP form and Google button | new, dropped into the existing `AuthShell` |

### The one genuinely new mechanism: JWKS handling

Read `kid` from the token header, look it up in the cached key set, and refetch on an unknown `kid` to survive
key rotation. **Rate-limit that refetch.** Without a limit, an attacker mints tokens carrying random `kid`
values and turns the validator into a request amplifier against Java — an unauthenticated DoS reachable from
any endpoint. Cache negative lookups too, and keep serving from the last-known-good key set if Java is
unreachable.

### Service-to-service calls are a separate mechanism

Neither direction uses a user JWT:

- **Java → Python** (`POST /internal/provisioning/organization`) — `X-Secret-Key`, following
  [api/services/mps_service_key_client.py](../api/services/mps_service_key_client.py).
- **Python → Java** (`POST /exec/http`, Phase 14) — the same shape, with the circuit-breaker fallback in §8.

Keeping user auth and service auth on separate credentials means a leaked service key cannot impersonate a
user, and a stolen user token cannot reach an internal endpoint.


## 4. Scope resolution — `get_user` is not modified

A `get_tenant_context` dependency in `api/saas/tenancy/` takes `Depends(get_user)` and resolves acting user,
active org, role and scope from `failte_auth`. **Zero lines change in the upstream seam file for this.**

It carries a *scope descriptor* `(scope_mode, tenant_root_id, active_organization_id)` — **not** a
materialized `reachable_organization_ids` set, which for a platform admin is every org in the system and is
stale the moment a vendor provisions a customer. The application filter, the RLS policy and the Java service
all translate that same descriptor into the same predicate, so three layers agree by construction.

Three entry paths:

- **Header auth** — the dependency, covering local JWT, Stack and `failte`.
- **API keys** — `_handle_api_key_auth` already *pins* `user.selected_organization_id` to the key's org. Our
  dependency re-declares the `X-API-Key` header rather than editing that upstream function, and **forces scope
  mode to `customer` even for a vendor-owned key**: a machine credential does not get subtree reach. This is a
  deliberate tightening over what a human with the same role could do, and belongs in the API docs.
- **WebSocket** — `get_user_ws` cannot reuse an HTTP-header dependency, so a parallel `_ws` entry point calls
  the same resolver body.

Userless paths — inbound telephony, embed and public-agent routes, webhook callbacks — have no user at all and
must enter scope explicitly via an `organization_scope(org_id, mode=...)` context manager. `api/AGENTS.md`
already singles these out as deriving `organization_id` from the payload.

Caching follows the `ensure_organization_bootstrapped` precedent — cheap enough to call on every request,
self-limiting to one indexed read: request-level memoization plus a ~30s process-local TTL cache of *facts*,
never decisions. Invalidation uses the existing `WorkerSyncManager` Redis pub/sub, which `api/AGENTS.md`
already mandates for cross-worker state; Java publishes to the same channel on role change. The TTL is the
backstop for a missed message, not the primary mechanism — so **revocation bypasses the cache synchronously**;
demotion need not.

Also closes a current gap: **membership is verified**, where today `selected_organization_id` is trusted
without checking that the user is actually a member.

## 5. Permission model — a product of two axes

Rather than six hand-written role definitions, the model is a product of two axes, which makes it mechanical
and hard to get subtly wrong.

- **Scope** from `org_type`: platform → everything; vendor → its own subtree; customer → itself.
- **Resource class** from the capability: **operational** (workflows, folders, campaigns, tools, knowledge
  base, recordings) vs **governance** (organizations, memberships, roles, API keys, telephony credentials,
  billing, quotas, branding, catalog publishing).

| | operational read | operational write | governance read | governance write |
|---|---|---|---|---|
| **admin** at level L | subtree(L) | subtree(L) | subtree(L) | subtree(L) |
| **member** at level L | subtree(L) | subtree(L) | subtree(L) | ✗ |

Four deliberate asymmetries:

- **`platform_member` is read-only outside the platform org.** A platform support engineer editing a
  customer's workflow leaves an audit trail saying "platform staff changed your agent" with no accountable
  path; the correct route is a `platform_admin` impersonating, which is logged as an impersonation. Vendor and
  customer members have no such restriction — a vendor member operating in their customer's workspace *is* the
  product.
- **Telephony is governance**, not operational, even though it feels like a day-to-day setting:
  `telephony_configurations` holds carrier credentials.
- **Deleting an organization is a parent-level capability.** A customer admin cannot delete their own org —
  that is a contractual decision belonging to the vendor. Likewise only the platform deletes vendors.
- **`vendor_admin` cannot impersonate.** They already have direct write access to everything in their subtree,
  so impersonation adds no capability — it only removes attribution, making the vendor's actions look like the
  customer's. Impersonation exists so platform staff can act *with* attribution, which is why it is restricted
  to the one role with no subtree write path of its own.

Role grants are bounded by the actor's own level: nobody grants a role above their own, and no self-promotion.

The full 6-role × ~35-capability matrix is generated from **one YAML source** into both a Python enum and a
Java enum, so the two enforcement points cannot drift. Enforcement is FastAPI dependencies raising
`HTTPException(403)` in the style of the existing `get_superuser`, not middleware; `require()` resolves target
ownership itself rather than trusting the handler, consistent with the rule already in `api/AGENTS.md`.

## 6. Isolation — application scoping and Postgres RLS

### 5.1 How scope reaches Postgres

There are 342 `async with self.async_session()` call sites but **exactly one engine**
([api/db/base_client.py:11](../api/db/base_client.py#L11)). A SQLAlchemy Core `begin` event on that engine
covers all 342 without touching one of them.

The hook writes four GUCs via `set_config(..., true)` — the function form of `SET LOCAL`, so
**transaction-scoped**. A plain `SET` here would leak one tenant's scope into the next pool checkout, which is
exactly the bug RLS exists to prevent.

Installed by **two appended lines** in [api/db/\_\_init\_\_.py](../api/db/__init__.py), a 3-line file —
covering routes, tasks, MCP and services alike, with no import cycle. This is the cheapest available seam.

**Fail-closed**: an unset ContextVar writes `scope_mode = 'none'`, which every policy denies. A code path that
forgets to enter scope returns zero rows loudly rather than everything silently.

`api/db/database.py` holds a second engine with **zero importers** — dead code, and the one way to get a
connection the hook does not cover. Delete it or document it.

### 5.2 Policy predicate

```sql
CREATE POLICY tenant_isolation ON <table>
  USING      (app.scope_mode() = 'platform' OR organization_id = ANY (app.scope_org_ids()))
  WITH CHECK (app.scope_mode() = 'platform' OR organization_id = ANY (app.scope_org_ids()));
```

`app.scope_org_ids()` is `STABLE` returning `int[]`, reading `failte_auth.org_node`. Why that shape rather
than a correlated `EXISTS`:

- `STABLE` lets the planner evaluate it **once per statement**, producing a small constant array.
- `organization_id = ANY (array)` is index-usable on the existing `ix_*_organization_id` indexes; a correlated
  `EXISTS` is a per-row subplan on the hottest tables in the system.
- It is *the same array* the application-level filter uses, so the two layers cannot disagree.
- A vendor with 500 customers yields a 500-element array — fine. 50,000 would not be, and that is the
  documented threshold for switching that branch to an indexed `EXISTS`.

`WITH CHECK` matters as much as `USING`: without it, a scoped session can *write* a row into another tenant.

> **"Java is read-only" is not a tenant-safety property.** A read-only connection with no scope reads every
> tenant. Java connects as a non-`BYPASSRLS` role and sets the same four GUCs per transaction — a HikariCP
> connection customiser plus `SET LOCAL` in a Spring transaction listener.

### 5.3 Transitively-scoped tables — backfill, do not join

`workflow_runs`, `workflow_definitions`, `queued_runs`, `embed_sessions`, `workflow_run_text_sessions` get a
real `organization_id` column. A policy that joins to the parent is wrong here for three compounding reasons:

1. `workflow_runs` is the analytics table. [api/db/filters.py](../api/db/filters.py) builds multi-predicate
   JSONB queries over it and `reports_client.py` aggregates it. A correlated subquery per row on that table is
   not a tax we can pay.
2. **RLS is recursive** — the policy on `workflows` also applies inside the subquery used by `workflow_runs`'
   policy. Nested policy evaluation on the hottest path is slow and very hard to debug.
3. The chains run two and three hops deep (`queued_runs → campaigns`, `workflow_run_text_sessions →
   workflow_runs → workflows`). Depth compounds the first two problems.

The denormalized column also **removes joins from queries we already run**, so it pays for itself
independently of RLS.

Note `workflows.organization_id` is currently **nullable**, with a legacy parallel `user_id`. Under RLS a NULL
`organization_id` makes the row invisible to *everyone*, including its owner — fail-closed, but it strands
legacy rows. Backfill from `user_id → users.selected_organization_id`. **Do not drop `user_id`** — it is
upstream's column and dropping it guarantees an autogenerate conflict on every sync.

### 5.4 Roles

| Role | Owns tables | BYPASSRLS | Used by |
|---|---|:--:|---|
| `dograh_migrate` | **yes** | **yes** | Alembic and Flyway only |
| `dograh_app` | no | no | FastAPI, ARQ workers, the Java service |
| `dograh_system` | no | **yes** | an enumerated allowlist of fleet-wide jobs |
| `dograh_readonly` | no | no | analytics, on a replica |

**`FORCE ROW LEVEL SECURITY` on every policied table, without exception.** Plain `ENABLE` exempts the table
owner, and `DATABASE_URL` points at `postgres` — the owner — today, so an `ENABLE`-only deployment would
silently apply no policies while looking correct in `pg_policies`. `FORCE` is the guard against the most
likely operational mistake in this repo.

Fleet-wide jobs use a **separate role on a separate engine**, not a `scope_mode = 'system'` GUC: a GUC can be
set by anything that can execute SQL in the session, including through an injection in a `text()` query — and
`execute_raw_query` exists at [api/db/base_client.py:14](../api/db/base_client.py#L14). A role-based bypass
cannot be forged from inside a session. ARQ tasks get no blanket bypass; each enters its campaign's org scope.

### 5.5 Enforcement is configuration, not code

The migration always creates the policies, so schema is uniform everywhere. Whether they are *enforced*
depends entirely on which role the connection string names. Zero code branches, zero feature flags in query
paths, and the posture of any deployment is answerable by reading one env var. `DEPLOYMENT_MODE=oss`
single-tenant installs are unaffected.

## 7. Tool-call standard and catalog

Today's flat `ToolParameter` list is expanded into JSON Schema by `tool_to_function_schema`
([api/services/workflow/tools/custom_tool.py](../api/services/workflow/tools/custom_tool.py)). The standard
replaces it with a **JSON Schema 2020-12 subset** — the intersection that survives all three LLM vendors,
where the real constraint is Gemini, which already needs
[gemini_json_schema_adapter.py](../api/services/pipecat/gemini_json_schema_adapter.py).

Conformance rule: *a spec is valid only if it round-trips through every registered vendor adapter without
loss.* `schema_version: int = 1` already exists on every definition variant and is the versioning hook; the
standard lands as `2`, with v1 read-compatible forever.

Catalog (`failte_auth.catalog_*`):

- A **spec** has a stable reverse-DNS id (`ai.failte.calendar.book_slot`), semver, JSON Schema params,
  category, required credential type, and conformance fixtures.
- **Visibility follows the hierarchy** — published `global` (platform) or `vendor` (that vendor's customers
  only). This is where catalog and tenancy intersect, and it is what makes the vendor tier worth something: a
  reseller ships their own vetted tool library.
- **Install** materialises a spec into an org as a normal `ToolModel` row through Python's existing
  `create_tool_for_user`, recording `spec_id` + `spec_version`. Upgrades are explicit, never silent.

## 8. `http_api` execution in Java

Java executes `http_api` only. `end_call`, `transfer_call`, `mcp` and `calculator` stay in Python — those
control the pipeline rather than call an API:

| Category | What the handler actually does |
|---|---|
| `end_call` | `FunctionCallResultProperties(run_llm=False)`, writes `call_disposition`, appends `call_tags`, then `end_call_with_reason()` — **terminates the pipeline** |
| `transfer_call` | `set_mute_pipeline(True)`, hold-music loop on the audio transport, Redis `TransferContext`, blocks on pub/sub — **touches the live media path** |
| `mcp` | Session opened at call start, held for the whole call, task-affine (must close in the same asyncio task — anyio cancel-scope constraint) |

**Moving `http_api` fixes two real defects.** [custom_tool.py](../api/services/workflow/tools/custom_tool.py)
builds a fresh `httpx.AsyncClient` per invocation — a new TCP + TLS handshake on every tool call — and the
credential lookup is an uncached DB round-trip every time. A pooled Java executor with a credential cache is
measurably faster than the current Python path; the added in-cluster hop is ~1-5 ms against a 5 s budget and a
customer API taking 200-2000 ms.

Three things the contract must pin:

- **`/tools/{uuid}/test` must call the same executor**, or test and live diverge on merge precedence
  (`{**preset, **llm}`), URL precedence (`preset < initial < gathered < llm`), or type-preserving body
  substitution — a support nightmare visible only in production.
- **SSRF validation re-implemented in Java must match** `validate_user_configured_service_url`
  ([api/utils/url_security.py](../api/utils/url_security.py)) exactly — private, loopback, link-local,
  multicast, reserved, CGNAT `100.64/10` — re-checked at call time because the URL is templated. Shared test
  vectors.
- **Circuit-break back to Python.** Keep `execute_http_tool` as the fallback; if Java is unreachable, live
  calls degrade to today's behaviour rather than failing.

Failure taxonomy (`classify_http_response`, `error_owner="user"` vs `"operator"`), `run_id` propagation into
loguru, and per-org Langfuse spans must all be fed from Java, or call debugging regresses.

---

# Part B — Development roadmap

Fifteen phases. Each names its goal, work, and a falsifiable exit criterion. Phases 1–4 ship a working
passwordless login before any tenancy work lands, so the riskiest new dependency — email delivery — is proven
early rather than discovered late.

**Standing rules for every phase.** `local` and `stack` auth keep working throughout. New endpoints follow the
`require_local_auth` pattern (router always mounted, gate at request time) so the OpenAPI spec and generated
SDKs do not vary by deployment. `bash scripts/lint.sh` and the full pytest suite — baseline **1892 passed** —
stay green. Run `scripts/generate_sdk.sh` **step 1 only**, per FORK.md.

## Phase 0 — Documentation

This document, plus splitting the detail out into `saas/docs/` as it stabilises. Close `AUTH-PROVIDER.md` with
the Spring Authorization Server decision. Mark `RBAC.md` superseded. Add `java/`, `api/db/__init__.py` and
`api/alembic/env.py` to FORK.md's seam table.

**Exit:** decisions recorded; no code touched.

## Phase 1 — Java service skeleton

Spring Boot 3.x in a new top-level `java/` directory — zero merge cost per FORK.md. Java 21. Flyway owning the
`failte_auth` schema and nothing else. Actuator health endpoint. Dockerfile built from **root context** to
match the existing two. Config from env vars in the existing `SCREAMING_SNAKE` convention.

Wire the plumbing now so later phases are pure feature work:

- `docker-compose.yaml` service block on `app-network`, explicit `environment:` map (the repo uses no
  `env_file:` anywhere), plus a healthcheck.
- `scripts/start_services_dev.sh` — an entry in **both** parallel arrays. `scripts/AGENTS.md` makes
  `start_services_dev.ps1` parity a hard rule. `stop_services.sh` needs nothing; it globs `run/*.pid`.
- `.github/workflows/docker-image.yml` — one matrix entry, plus the name in `inspect_digests` and
  `create_manifests`, currently hardcoded to two.
- `ui/src/app/api/failte/[...path]/route.ts` — copy the existing catch-all proxy verbatim, swapping the
  backend resolver, for same-origin browser access with no ingress config in any of the four topologies.

**Exit:** `docker compose up` brings the service healthy; CI builds and pushes both architectures.

## Phase 2 — Email delivery

The highest-risk dependency, therefore first. Choose a transactional provider. Set up a dedicated sending
domain with SPF, DKIM and DMARC. Implement the send abstraction and one template. Wire bounce and complaint
webhooks. Add delivery-latency monitoring.

**Exit:** a test send reaches Gmail, Outlook and a corporate Google Workspace inbox — **not** spam — with
median delivery under 10 seconds, and DMARC reports show alignment.

## Phase 3 — Email OTP sign-in, end to end

`identity`, `identity_credential`, `otp_challenge`. The two endpoints from §2.2 with every rule in that
section: always-200 start, challenge-bound codes, 5 attempts then burn, 10-minute expiry, single use,
constant-time compare, dual-axis rate limits. Spring Authorization Server issuing JWTs with `typ`, exposing
JWKS.

Python: `AUTH_PROVIDER=failte` — a **3-line branch** in `get_user` after the `local` branch
([api/services/auth/depends.py](../api/services/auth/depends.py)), local JWKS validation with cached keys, JIT
user mirroring through the existing `get_or_create_user_by_provider_id`.

UI: an OTP form in the existing `AuthShell`
([ui/src/components/auth/AuthShell.tsx](../ui/src/components/auth/AuthShell.tsx)), two steps — email, then
code. Add `'failte'` to the `AuthProvider` union in [ui/src/lib/auth/types.ts](../ui/src/lib/auth/types.ts), a
config branch, and two optional `HealthResponse` fields. The existing cookie chain is unchanged.

**Exit:** a new user signs up and an existing user signs in by email code, in a real browser, on a deployed
environment. `local` and `stack` still work.

## Phase 4 — Google sign-in

OAuth2 authorization code + PKCE via `spring-boot-starter-oauth2-client`. `state` and `nonce` verified;
`aud`/`iss` validated. Account linking **only on `email_verified: true`** (§2.3). Google button and divider in
`AuthShell` — the current `LoginForm` has neither, so this is purely additive.

**Exit:** sign-in with Google resolves to the *same* identity as the OTP flow for the same verified address;
a Google account with an unverified email does **not** link, proven by a test.

## Phase 5 — Tenancy tree

`org_node`, `membership`, invitations, with every constraint from §1 — the shape CHECK, the typed parent FK,
and the two composite membership FKs. Java tenancy APIs: create vendor, create customer, invite, set role,
list subtree. The `POST /internal/provisioning/organization` endpoint on the Python side for the shell rows.

**Exit:** four operations are **impossible**, each proven by a failing-insert test — a user under vendor A
joining an org under vendor B; a platform admin holding a customer membership; a four-level tree; an
`org_node` row whose `tenant_root_id` disagrees with its parent.

## Phase 6 — Data migration

Alembic (`saas_`-prefixed revisions) plus Flyway. Create the platform node and **exactly one vendor, "Failte
AI Direct"**; attach every existing org under it as `customer`; mark every existing membership `admin`.

That encodes the status quo honestly rather than guessing at demotions — demote deliberately afterwards, in
the product, with an audit trail. The single default vendor is what lets constraints apply unconditionally
with no legacy special case.

**One destructive step needing a human-reviewed dry run:** `is_superuser` users become platform admins, and
the §1 constraints then forbid them holding customer memberships — those rows must be deleted. If a superuser
genuinely needs to operate inside a tenant, that is what impersonation is for.

**Exit:** the dry-run report is reviewed and signed off; the migration is reversible up to the deletion step.

## Phase 7 — Tenant context, log-only

`TenantContext`, the resolver, the YAML-generated capability matrix, and `require()` guards on new routes in
**log-only mode** — denials are logged, not enforced. Membership verification switched on.

**Exit:** one week of clean deny-logs in production. Canary tests (`test_auth_depends.py`,
`test_organization_bootstrap.py`) green.

## Phase 8 — Enforce capabilities, ship consoles

Flip `require()` to enforcing. Platform and vendor consoles in `ui/src/saas/`; org switcher; member
management; role-gated routes in [ui/src/middleware.ts](../ui/src/middleware.ts) — remember `PUBLIC_PATHS`
needs any new public auth page, and the matcher excludes `/api/*`.

**Exit:** a vendor admin provisions a customer org and invites its first admin, end to end, in the UI.

## Phase 9 — Transitive `organization_id`

Add nullable column + index → application sets it on insert → `BEFORE INSERT` trigger derives it from the
parent when NULL → batched backfill by id range → **a later, separate deploy** sets `NOT NULL` → `BEFORE
UPDATE` trigger rejects changes, or a row can be walked across tenants. Backfill `workflows.organization_id`
from `user_id → users.selected_organization_id`.

**Schema → code → constraint, three deploys, never one.** Adding a nullable column, deploying code that
populates it, and only then tightening is what keeps a rollback survivable.

**Exit:** all five tables `NOT NULL` with zero orphans; the suite green.

## Phase 10 — Application scope helper

The shared filter helper through the `db/` clients, translating the same scope descriptor the RLS policy will
use. Add `("saas","db")` to `INTERNAL_TOOLING_PREFIXES` in
[api/tests/test_db_layer_boundary.py](../api/tests/test_db_layer_boundary.py) — otherwise `api/saas/db/rls.py`
fails that guard for importing sqlalchemy.

**Exit:** every org-scoped query goes through the helper, asserted by a boundary test.

## Phase 11 — RLS created, enforcement off

The `app` schema functions, four roles, grants, `ENABLE` + `FORCE`, policies, and the GUC hook on both the
Python engine and the Java pool. Production keeps naming the bypass role, so nothing changes behaviourally.

Run **shadow mode**: sampled queries executed through both roles, row-count divergence logged. A divergence is
either a missing policy or an over-broad application filter — either is a finding. Retire the comparison once
it is silent for a week.

**Exit:** shadow divergence silent for one week in staging *and* production.

## Phase 12 — RLS enforced

Flip `DATABASE_URL` to the non-bypass role, Python and Java both. Keep the bypass role available for a fast
rollback.

**Exit:** a cross-tenant read returns zero rows in the RLS test suite, including through the Java pool.

## Phase 13 — Tool-standard catalog

`catalog_*` tables, the JSON Schema 2020-12 subset, the vendor-adapter round-trip conformance suite, publish
and approve flows, hierarchy-scoped visibility, and install-into-org via `create_tool_for_user`.

**Exit:** a platform-published spec and a vendor-published spec each install into a customer org and run on a
real call; conformance fixtures run in CI.

## Phase 14 — Java `http_api` executor

The `POST /exec/http` contract, connection pooling, credential caching, the SSRF vectors shared with Python,
failure taxonomy and `run_id`/Langfuse propagation, `/tools/{uuid}/test` repointed at the same executor, and
the circuit-breaker fallback to `execute_http_tool`.

**Exit:** identical results from Java and Python across the shared fixture set; a measured p50/p95 improvement
on repeat calls to the same host; killing the Java service mid-call degrades to the Python path without a
failed call.

## Phase 15 — Impersonation, audit, and the commercial layer

Platform-admin impersonation with the impersonator recorded in the token, the tenant context, and every
written row. `audit_log` append-only **enforced by revoking UPDATE/DELETE from the app role**, not by
convention — otherwise the strongest thing we can tell an enterprise customer about impersonation is
unenforceable. Customer admins can see impersonations into their own org. Then billing rollup, quotas down the
tree, white-label domains.

**Exit:** an impersonation session is fully reconstructable from the audit log, and the impersonated org's
admin can see it.

---

## Ordering decisions worth defending

- **Email before auth (2 before 3).** Deliverability is the only dependency that can fail in a way no code
  change fixes quickly. Proving it first is cheap; discovering it at launch is not.
- **Auth before tenancy (3–4 before 5).** A working login is independently valuable and exercises the whole
  Java↔Python↔UI path on the simplest possible feature.
- **RLS after application scoping (11–12 after 10).** If RLS lands first, every missing application filter
  surfaces as a mysterious empty result and gets "fixed" by widening scope. Landing scoping first makes RLS a
  *confirmation* of an invariant we already hold, and shadow mode measures exactly that.
- **Catalog and executor last (13–14).** They depend on tenancy for visibility scoping and on the Java service
  being operationally proven. Neither blocks revenue.

---

## Upstream delta — the whole cost

Per FORK.md, new files are free and every line in an upstream file is a conflict paid on every sync.

| File | Change | Lines |
|---|---|---|
| [api/db/models.py](../api/db/models.py) | `organization_id` on 5 transitive models. **Nothing on User/Organization/membership** | ~10 |
| [api/routes/main.py](../api/routes/main.py) | routers appended, 2 optional `HealthResponse` fields | 6 |
| [api/services/auth/depends.py](../api/services/auth/depends.py) | 3-line `failte` branch in `get_user`; **zero for scope** | 3 |
| [api/db/\_\_init\_\_.py](../api/db/__init__.py) | RLS hook install (**new seam**) | 2 |
| [api/alembic/env.py](../api/alembic/env.py) | import so autogenerate sees `api/saas/db/models.py` (**new seam**) | 1 |
| [api/tests/test_db_layer_boundary.py](../api/tests/test_db_layer_boundary.py) | allowlist `("saas","db")` | 1 |
| [api/services/workflow/tools/custom_tool.py](../api/services/workflow/tools/custom_tool.py) | delegate to the Java executor with local fallback | ~15 |
| `ui/src/middleware.ts`, `ui/src/lib/auth/*`, AuthShell pages | `'failte'` in the provider union, OTP + Google forms, role-gated routes | ~120 |

Everything else is new files in `api/saas/`, `ui/src/saas/` and `java/` — free.

Two entries are **new to FORK.md's seam table** and should be added deliberately: `api/db/__init__.py` and
`api/alembic/env.py`. Both are append-only two-line changes to short files — about the cheapest seams
available — and both are load-bearing for the whole design.

## Pre-existing issues found, to fix in passing

Small, real, and each one touches this work:

1. **`create_jwt_token` has no `typ` claim** ([api/utils/auth.py](../api/utils/auth.py)) — a second token kind
   cannot be safely introduced without it. Fix in Phase 3.
2. **PyJWT is not declared in `api/requirements.txt`** — it is present only transitively via `fastmcp` and
   `langfuse`, while `api/utils/auth.py` imports it directly. A dependency bump elsewhere breaks auth.
3. **`create_user_with_email(name=...)` accepts `name` and never assigns it**
   ([api/db/user_client.py](../api/db/user_client.py)) — signup echoes a name it did not store.

## Open questions

- **Own-IdP scope creep** beyond passwordless: MFA as a genuine second factor, enterprise SSO/SAML.
- **Billing attribution** across the tree. Does a vendor get aggregated billing across their customers, and
  does the platform bill the vendor or the customer? Does a direct-billed customer still count toward the
  vendor's volume tier?
- **White-labelling.** Resolving a tenant from the `Host` header conflicts with `ui/src/middleware.ts`'s
  module-scoped, TTL-less provider cache. Needs its own bounded cache.
- **Quotas down the tree.** An effective-config resolver walking two hops up is easy; making MPS respect a
  vendor-level cap is not, and may not be possible without an MPS change.
- **Provisioning inversion.** `ensure_organization_bootstrapped` assumes `created_by` is a member and runs
  lazily on an authenticated request. A vendor-created customer org breaks both assumptions — until its first
  admin signs in, the org is never bootstrapped: no model configuration, no SIP. Make provisioning explicit at
  creation time via an ARQ task, keeping the lazy path only for self-serve signup.
- **Catalog spec deprecation** and forced-upgrade policy.
- **Keeping the Java and Python SSRF vectors in sync** without a shared fixture file.
- **There is no CD workflow for the Docker stack at all.** `docker-image.yml` only builds and pushes; deploys
  are operator-driven via `update_remote.sh` / `rolling_update.sh`. The Java service inherits that, and it
  should be a decision rather than a surprise.
