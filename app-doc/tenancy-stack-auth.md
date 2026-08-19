# Three-level tenancy on Stack Auth

> **Status: design of record for identity.** Supersedes the Spring Authorization Server decision in
> [`tenancy-auth-roadmap.md`](./tenancy-auth-roadmap.md) and its Phases 1–4, and closes the open decision in
> [`saas/docs/AUTH-PROVIDER.md`](../saas/docs/AUTH-PROVIDER.md).
> **The hierarchy, RBAC, RLS and catalog designs in the roadmap carry over intact** — only the token issuer changes.
> [`saas/docs/FORK.md`](../saas/docs/FORK.md) remains binding on where code may live.

## Context

The roadmap builds our own IdP in Java because we need two things: **passwordless sign-in** (email OTP + Google)
and a **three-level tenant tree** with admin/member at each level.

```
Platform (us)            admin · member
└── Vendor (reseller)    admin · member
    └── Customer (the end company we build agents for)   admin · member
```

Stack Auth — already integrated, open source, self-hostable — does the sign-in half natively: magic-link/OTP,
Google OAuth, and its own transactional mail. It does **not** do hierarchy: its teams are flat. That was already
the recorded finding in [AUTH-PROVIDER.md](../saas/docs/AUTH-PROVIDER.md) — *"No mainstream identity provider
models a multi-level organization hierarchy natively."* Clerk, WorkOS and Auth0 are the same.

So **the tree lives in our Postgres regardless of provider**, which means adopting Stack costs us nothing on the
tenancy design and saves us the entire identity build. Roadmap Phases 1–4 — Java skeleton, email infrastructure,
the OTP protocol, Google OAuth — collapse to configuration.

Note: Stack Auth's documentation now serves from `docs.hexclave.com`, and its session cookies carry a
`hexclave-` prefix alongside the legacy `stack-` one. The repo already handles both —
`/^(?:__Host-)?(?:stack|hexclave)-(?:access|refresh)(?:-|$)/` at
[ui/src/app/impersonate/route.ts:37](../ui/src/app/impersonate/route.ts).

### Decisions taken

| Decision | Choice |
|---|---|
| Identity provider | **Stack Auth, self-hosted in the EU.** Supersedes the Spring Authorization Server choice |
| Sign-in methods | **Email OTP / magic link + Google. No passwords**, configured in Stack, not built by us |
| Java service | **Later, and only** for the tool-standard catalog and the `http_api` executor. Never for identity |
| Hierarchy storage | Sidecar **`saas` Postgres schema**, Python/Alembic-owned |
| Stack teams | **Retired.** Stack is identity only; the acting org comes from our own DB |
| Token validation | **Local ES256 JWKS**, replacing the per-request `/users/me` hop |
| Vendor-less customers | A permanent platform-owned **house vendor, "Failte AI Direct"** |
| Isolation | Application-level scoping **and** Postgres RLS — unchanged from the roadmap |
| Cross-vendor membership | **Forbidden**, enforced structurally in the DB — unchanged from the roadmap |

### What already exists

Upstream is genuinely multi-tenant: `organizations`, `organization_users` M2M,
`users.selected_organization_id`, `organization_id` FKs on ~20 tables. Missing exactly two things — **roles**
(no `role` column anywhere in [api/db/models.py](../api/db/models.py); only boolean `users.is_superuser`) and
**hierarchy** (organizations are flat).

Stack is wired in through a deliberate seam: `AUTH_PROVIDER` selects `local` or `stack`, and the UI discovers the
active provider at runtime from `/api/v1/health`, so switching needs no rebuild. Impersonation already exists and
is Stack-native ([api/routes/superuser.py](../api/routes/superuser.py) plus the cookie surgery in
[ui/src/app/impersonate/route.ts](../ui/src/app/impersonate/route.ts)).

**No email infrastructure of our own.** Verified by grep: zero hits for
`smtplib|aiosmtplib|MIMEText|sendgrid|resend|mailgun|postmark|SESClient`, no mail library in
`api/requirements.txt`, no `SMTP_*`/`MAIL_*` env, no templates. Under this design we do not need any to ship
tenancy — see §7.

---

# Part A — Architecture

## 1. Why Stack cannot hold the hierarchy

Three independent reasons. Any one of them is sufficient; together they settle it.

**Teams are flat.** Stack's own documentation describes team structures without nesting: users *switch between*
teams rather than navigate a hierarchy. Permissions compose recursively — an `admin` permission can contain
`member` — and are scoped either `team` or `project`, but neither axis expresses a parent-child relationship
between tenants.

**The access token carries no team or role claim.** Stack publishes a JWKS at
`<STACK_AUTH_API_URL>/api/v1/projects/<project-id>/.well-known/jwks.json`; tokens are ES256 with `aud` = the
project id and `sub` = the user id. There is no `selected_team_id` claim. So any design that derives the acting
organization from Stack forces a network call to Stack on **every authenticated request**:

| Dependency | Call sites |
|---|---|
| `Depends(get_user)` | 118 |
| `Depends(get_user_with_selected_organization)` | 15 |
| `Depends(get_superuser)` | 2 |
| `Depends(get_user_ws)` | 1 |

136 sites. That is exactly what happens today —
[api/services/auth/stack_auth.py:32](../api/services/auth/stack_auth.py) calls `/api/v1/users/me` per request,
building a fresh `aiohttp.ClientSession` each time, with no pooling — and it means a Stack outage takes down the
whole API including live telephony, which authenticates over WebSocket.

**A vendor admin must act inside a customer org they are not a member of.** That is the entire point of the
vendor tier, and Stack team permissions cannot represent it: permissions attach to a team the user belongs to.
Making the vendor a member of every customer team would work only by destroying the distinction we are building.

The conclusion is clean rather than grudging: **Stack owns authentication, we own authorization.** Which is the
correct split anyway — authorization data is ours, changes at our cadence, and must be readable by an RLS policy
inside our own database.

### The requirement being removed

Today [api/services/auth/depends.py](../api/services/auth/depends.py) hard-requires a Stack team:

```python
selected_team_id: str | None = stack_user.get("selected_team_id")
if not selected_team_id and stack_user.get("selected_team"):
    selected_team_id = stack_user["selected_team"].get("id")
if not selected_team_id:
    raise HTTPException(status_code=400, detail="No team selected")
```

and then maps it 1:1 onto `organizations.provider_id`. Removing that requirement is what unblocks JWKS-only
validation. Existing rows keep their Stack team id in `provider_id` — nothing is rewritten; new organizations
simply get a synthetic id, exactly as `local` mode already does (`org_{user.provider_id}`,
[api/routes/auth.py:42](../api/routes/auth.py)).

Worth noting how little we lose: **Stack team permissions never reach the backend at all today.** They are read
client-side only — [ui/src/context/OrgConfigContext.tsx](../ui/src/context/OrgConfigContext.tsx) and
`getRedirectUrl` in `ui/src/lib/utils.ts` — and `OrgConfigContext` already hardcodes `[{ id: 'admin' }]` for
non-Stack providers. Replacing that source with our own endpoint deletes a provider-specific branch rather than
adding one.

## 2. Hierarchy schema — declarative, no triggers

New tables live in a `saas` schema, owned by Python and Alembic. `public.users` and `public.organizations` are
**never written by this layer**; cross-schema foreign keys are legal in one database, so `saas.*` references
upstream's rows without touching upstream's models. Per [FORK.md](../saas/docs/FORK.md), every line in an upstream
file is a conflict paid on every sync, and this keeps `UserModel`, `OrganizationModel` and the
`organization_users` association table byte-identical.

```sql
CREATE SCHEMA saas;
CREATE TYPE saas.org_type AS ENUM ('platform','vendor','customer');
CREATE TYPE saas.org_role AS ENUM ('admin','member');

CREATE TABLE saas.org_node (
  organization_id        int PRIMARY KEY REFERENCES public.organizations(id) ON DELETE CASCADE,
  org_type               saas.org_type NOT NULL,
  parent_organization_id int NULL,
  parent_org_type        saas.org_type NULL,
  tenant_root_id         int NOT NULL,
  name                   text NOT NULL,
  slug                   citext UNIQUE,
  branding               jsonb NOT NULL DEFAULT '{}',
  UNIQUE (organization_id, org_type),
  UNIQUE (organization_id, tenant_root_id),
  CHECK (
     (org_type='platform' AND parent_organization_id IS NULL     AND parent_org_type IS NULL    AND tenant_root_id = organization_id)
  OR (org_type='vendor'   AND parent_organization_id IS NOT NULL AND parent_org_type='platform' AND tenant_root_id = organization_id)
  OR (org_type='customer' AND parent_organization_id IS NOT NULL AND parent_org_type='vendor'   AND tenant_root_id = parent_organization_id)
  ),
  FOREIGN KEY (parent_organization_id, parent_org_type)
    REFERENCES saas.org_node (organization_id, org_type)
);

-- pins each user to exactly one tenant root
CREATE TABLE saas.user_tenant (
  user_id        int PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  tenant_root_id int NOT NULL REFERENCES saas.org_node(organization_id),
  UNIQUE (user_id, tenant_root_id)
);

CREATE TABLE saas.membership (
  user_id         int NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  organization_id int NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  role            saas.org_role NOT NULL,
  tenant_root_id  int NOT NULL,
  PRIMARY KEY (user_id, organization_id),
  FOREIGN KEY (organization_id, tenant_root_id) REFERENCES saas.org_node   (organization_id, tenant_root_id),
  FOREIGN KEY (user_id,         tenant_root_id) REFERENCES saas.user_tenant(user_id,         tenant_root_id)
);

CREATE TABLE saas.invitation (
  id uuid PRIMARY KEY, organization_id int NOT NULL, email citext NOT NULL,
  role saas.org_role NOT NULL, token_hash text NOT NULL, invited_by int NOT NULL,
  expires_at timestamptz NOT NULL, accepted_at timestamptz NULL
);

CREATE TABLE saas.audit_log (...);  -- append-only, enforced by revoking UPDATE/DELETE from the app role
```

Six roles from two enums: a role is the pair `(org_node.org_type, membership.role)`. This keeps the enum stable
if a fourth tenant level ever appears.

### The four invariants, and why each is structural

**Depth is capped at three by referential integrity, not policy.** The CHECK pins `parent_org_type` from
`org_type`, and the composite FK `(parent_organization_id, parent_org_type) → org_node (organization_id,
org_type)` forces a customer's parent to be a vendor and a vendor's parent to be the platform. A fourth level
would need `parent_org_type='customer'`, which no CHECK arm permits. It is not forbidden by convention; it is
unrepresentable.

**No cross-vendor membership, with no trigger.** `tenant_root_id` is never NULL — platform and vendor nodes are
their own root — and a user's `tenant_root_id` is a single scalar. Every membership they hold must therefore
resolve to the same root, and **no INSERT satisfies both composite FKs across two vendors.** "Platform is its own
root" is load-bearing: with a NULL root both FKs go unenforced under `MATCH SIMPLE`, and a platform user could
quietly acquire a vendor membership.

**Subtree queries are equality, not recursion.** The denormalization that enforces the constraint also serves the
query:

| Actor scope | Predicate | Cost |
|---|---|---|
| platform | *(unrestricted)* | — |
| vendor, acting in org `V` | `tenant_root_id = V` | one index scan |
| customer, acting in org `C` | `organization_id = C` | PK lookup |

No closure table, no materialized path, no recursive CTE in the request path. If a fourth *tenant* level is ever
introduced, the right move is `ltree` on a `path` column with a GiST index. Do not build it now.

**`saas` never writes `public`.** Every relationship to upstream's rows is a foreign key. Creating an
organization still goes through Python's own path; this layer only classifies and connects.

### What drops versus the roadmap

`identity`, `identity_credential` and `otp_challenge` disappear entirely — Stack owns credentials, and
`public.users.provider_id` already holds the Stack user id, so it is the join key. Roadmap §2 (passwordless
identity), all of its OTP rules, and the Google account-linking rule become Stack's configuration rather than our
code. One rule from §2.3 is still worth knowing as an operator: **link a Google identity to an existing email
identity only when Google's ID token asserts `email_verified: true`** — verify Stack's behaviour here matches,
because it is the highest-severity rule in any account-linking design.

Also unchanged from roadmap §6.3: `organization_id` gets added to the five transitively-scoped tables
(`workflow_runs`, `workflow_definitions`, `queued_runs`, `embed_sessions`, `workflow_run_text_sessions`). That is
the only change to [api/db/models.py](../api/db/models.py), about ten lines. `workflows.organization_id` is
currently **nullable** with a legacy parallel `user_id`; under RLS a NULL `organization_id` makes the row
invisible to everyone including its owner, so backfill from `user_id → users.selected_organization_id` — and
**do not drop `user_id`**, it is upstream's column and dropping it guarantees an autogenerate conflict on every
sync.

## 3. Vendor-less customers — the house vendor

Most customers are direct: we sell to them, no reseller involved. They are modelled as customers of **one
permanent platform-owned vendor node, "Failte AI Direct"** — not as a second shape in the schema. It is not a
migration artifact; it is where every direct customer lives permanently, and where every self-serve signup lands.

Why this rather than a special case:

- The CHECK stays at exactly one arm per `org_type`, and `tenant_root_id` stays non-NULL everywhere. All four
  invariants above apply unconditionally, with no legacy branch to reason about.
- Everything that resolves one hop up — branding, catalog visibility, quotas, billing rollup — keeps working for
  direct customers, resolving to our own defaults instead of a reseller's.
- Our staff administer direct customers with the ordinary `vendor_admin` role. "Manage all direct customers"
  needs no code path of its own.

**The trade-off, stated plainly.** Every direct customer shares `tenant_root_id = <house vendor>`, so the
composite-FK constraint does **not** structurally forbid one user holding memberships in two different direct
customers, the way it does across two real vendors. Access still requires an explicit `saas.membership` row —
nothing is reachable without one — but the database will not catch an over-broad grant there. This is the same
latitude a real vendor's staff already have inside their own subtree, which is deliberate: a vendor member
operating in their customer's workspace *is* the product.

**Alternative, if that latitude is unacceptable.** Let `customer` parent directly onto `platform` and be its own
root, by adding a second CHECK arm:

```sql
OR (org_type='customer' AND parent_organization_id IS NOT NULL
    AND parent_org_type='platform' AND tenant_root_id = organization_id)
```

Direct customers then get full structural isolation from one another. The cost is two shapes for `customer`, a
`tenant_root_id` that is sometimes self and sometimes parent, and effective-config resolution that must handle a
missing vendor hop. Take this only if a specific compliance requirement demands it; otherwise the house vendor is
the simpler correct answer.

## 4. How every API request gets validated

The usual worry about an external IdP is that each of the 136 authenticated endpoints depends on it being up.
Under this design **it does not** — and that is a strict improvement on today, where every request does call
Stack.

### Today, `stack` mode

```
UI login  →  Stack                                            → Stack session
every request  →  interceptor adds  Authorization: Bearer <token>
Python get_user  →  stackauth.get_user()  →  HTTP to Stack /users/me   ← network, every request
                                          →  requires selected_team_id → organization
```

### With `failte` mode

```
UI login  →  Stack (magic link / OTP or Google)               → Stack session
every request  →  interceptor adds  Authorization: Bearer <token>    ← byte-for-byte identical
Python get_user  →  _handle_failte_auth  →  verify ES256 vs Stack's JWKS   ← local crypto, no network
                                          →  get_or_create_user_by_provider_id(payload["sub"])
```

Stack's public keys are fetched once and cached. **Python makes no per-request call to Stack.** Stack can be
entirely down and existing sessions keep working; only new logins fail. This is an availability requirement, not
an optimisation — inbound telephony rides on `get_user_ws`.

### The one genuinely new mechanism: JWKS handling

Read `kid` from the token header, look it up in the cached key set, and refetch on an unknown `kid` to survive
key rotation. **Rate-limit that refetch.** Without a limit, an attacker mints tokens carrying random `kid` values
and turns the validator into a request amplifier against Stack — an unauthenticated DoS reachable from any
endpoint. Cache negative lookups too, and keep serving from the last-known-good key set if Stack is unreachable.
Validate `aud` against the project id and reject on any failure.

### What changes on the Python side

One new file, `api/saas/auth/depends_failte.py`, plus a **three-line branch** in `get_user`
([api/services/auth/depends.py](../api/services/auth/depends.py)) mirroring the shape of the existing `local`
branch so a merge conflict resolves obviously. Upstream's `stack` branch is left untouched and keeps working.
**The 136 call sites change nothing** — they take `user: UserModel = Depends(get_user)` and are indifferent to
where the token came from. That indifference is the whole reason the `AUTH_PROVIDER` seam is worth using rather
than replacing.

`stackauth.get_user()` survives, demoted from a per-request call to a **per-new-user profile fetch**: we call it
only when `get_or_create_user_by_provider_id` created the row, or the email is missing. Building a fresh
`aiohttp.ClientSession` per call is acceptable once per user; it was not acceptable once per request.

### The three auth paths

| Path | Change needed |
|---|---|
| **Header JWT** (the main path) | The new `failte` branch. Three lines |
| **`X-API-Key`** | **None.** API keys are Python-issued, stored in Python's `api_keys` table, validated by Python. Stack is not involved at any point |
| **WebSocket** (`get_user_ws`) | **None.** It delegates to `get_user`, so it inherits the branch for free — but verify explicitly, since telephony rides on it |

### What changes on the JavaScript side

| Thing | Change |
|---|---|
| `setupAuthInterceptor` in [ui/src/lib/apiClient.ts](../ui/src/lib/apiClient.ts) | **none** — it calls `getAccessToken()` and does not know the provider |
| `AuthContextType` | **none** — it already abstracts providers behind `getAccessToken` / `redirectToLogin` / `logout` |
| Cookie names and the session round-trip | **none** |
| `AuthProvider` union in [ui/src/lib/auth/types.ts](../ui/src/lib/auth/types.ts) | one line: add `'failte'` |
| `ui/src/saas/FailteProviderWrapper.tsx` | new file — wraps Stack's client app, so mostly a re-export of `StackProviderWrapper` |
| Org switcher, consoles | new, see §7 |

## 5. Scope resolution — `get_user` is not modified

A `get_tenant_context` dependency in `api/saas/tenancy/` takes `Depends(get_user)` and resolves acting user,
active org, role and scope from `saas`. **Zero lines change in the upstream seam file for this.**

It carries a *scope descriptor* `(scope_mode, tenant_root_id, acting_organization_id, role)` — **not** a
materialized `reachable_organization_ids` set, which for a platform admin is every org in the system and is stale
the moment a vendor provisions a customer. The application filter, the RLS policy and any future service all
translate that same descriptor into the same predicate, so the layers agree by construction.

**Reachability rule.** The acting organization is allowed if the user holds a membership on it, **or** holds a
membership on an ancestor within the same `tenant_root_id`. Platform members reach everything; a vendor reaches
its own subtree by equality on `tenant_root_id`; a customer reaches only itself.

Three entry paths:

- **Header auth** — the dependency.
- **API keys** — `_handle_api_key_auth` already *pins* `user.selected_organization_id` to the key's org. Our
  dependency re-declares the `X-API-Key` header rather than editing that upstream function, and **forces scope
  mode to `customer` even for a vendor-owned key**: a machine credential does not get subtree reach. This is a
  deliberate tightening over what a human with the same role could do, and belongs in the API docs.
- **WebSocket** — `get_user_ws` cannot reuse an HTTP-header dependency, so a parallel `_ws` entry point calls the
  same resolver body.

Userless paths — inbound telephony, embed and public-agent routes, webhook callbacks — have no user at all and
must enter scope explicitly via an `organization_scope(org_id, mode=...)` context manager. `api/AGENTS.md`
already singles these out as deriving `organization_id` from the payload.

Caching follows the `ensure_organization_bootstrapped` precedent — cheap enough to call on every request,
self-limiting to one indexed read: request-level memoization plus a ~30s process-local TTL cache of *facts*,
never decisions. Invalidation uses the existing `WorkerSyncManager` Redis pub/sub, which `api/AGENTS.md` already
mandates for cross-worker state. The TTL is the backstop for a missed message, not the primary mechanism — so
**revocation bypasses the cache synchronously**; demotion need not.

This also closes a current gap: **membership is verified**, where today `selected_organization_id` is trusted
without checking that the user is a member at all. `is_user_member_of_organization` exists at
[api/db/organization_client.py:112](../api/db/organization_client.py) but the auth path never calls it.

## 6. Permission model — a product of two axes

Unchanged from the roadmap. Rather than six hand-written role definitions, the model is a product of two axes,
which makes it mechanical and hard to get subtly wrong.

- **Scope** from `org_type`: platform → everything; vendor → its own subtree; customer → itself.
- **Resource class** from the capability: **operational** (workflows, folders, campaigns, tools, knowledge base,
  recordings) vs **governance** (organizations, memberships, roles, API keys, telephony credentials, billing,
  quotas, branding, catalog publishing).

| | operational read | operational write | governance read | governance write |
|---|---|---|---|---|
| **admin** at level L | subtree(L) | subtree(L) | subtree(L) | subtree(L) |
| **member** at level L | subtree(L) | subtree(L) | subtree(L) | ✗ |

Four deliberate asymmetries:

- **`platform_member` is read-only outside the platform org.** A platform support engineer editing a customer's
  workflow leaves an audit trail saying "platform staff changed your agent" with no accountable path; the correct
  route is a `platform_admin` impersonating, which is logged as an impersonation.
- **Telephony is governance**, not operational, even though it feels like a day-to-day setting:
  `telephony_configurations` holds carrier credentials.
- **Deleting an organization is a parent-level capability.** A customer admin cannot delete their own org — that
  is a contractual decision belonging to the vendor. Likewise only the platform deletes vendors.
- **`vendor_admin` cannot impersonate.** They already have direct write access to everything in their subtree, so
  impersonation adds no capability — it only removes attribution.

Role grants are bounded by the actor's own level: nobody grants a role above their own, and no self-promotion.

**One simplification against the roadmap.** With no Java enforcement point, there is nothing for the matrix to
drift against, so the YAML-source-generating-two-enums machinery is unnecessary. One plain Python module,
`api/saas/rbac/capabilities.py`. Enforcement stays FastAPI dependencies raising `HTTPException(403)` in the style
of the existing `get_superuser`, not middleware; `require()` resolves target ownership itself rather than
trusting the handler, consistent with the rule already in `api/AGENTS.md`.

## 7. Replacing the Stack team switcher

Today the acting org is switched by Stack's `SelectedTeamSwitcher`
([ui/src/components/layout/SidebarTeamSwitcher.tsx](../ui/src/components/layout/SidebarTeamSwitcher.tsx)), which
writes `setSelectedTeam` and hard-reloads. Under a tree that cannot work: a vendor admin switching into a
customer org is not a member of that customer's Stack team. The switcher becomes ours.

New router `api/saas/routes/tenancy.py`, appended to [api/routes/main.py](../api/routes/main.py):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/saas/me/context` | acting org, org_type, role, capabilities — replaces the UI's `listPermissions(selectedTeam)` |
| `GET /api/v1/saas/orgs` | the reachable subtree; one index scan on `tenant_root_id` |
| `POST /api/v1/saas/me/active-organization` | validate reachability, then write `users.selected_organization_id` |
| `POST /api/v1/saas/orgs` | create a vendor or customer, capability-gated |
| `POST /api/v1/saas/orgs/{id}/members` | invite by email — reuses the existing `stackauth.find_users_by_email` |

UI, all new files under `ui/src/saas/` except the seams noted in §4:

- `ui/src/saas/OrgSwitcher.tsx` replaces `SidebarTeamSwitcher` when `provider === 'failte'`.
- [ui/src/context/OrgConfigContext.tsx](../ui/src/context/OrgConfigContext.tsx) sources permissions from
  `/me/context` instead of Stack — which also deletes its hardcoded `[{ id: 'admin' }]` fallback.
- Role-gated routes in [ui/src/middleware.ts](../ui/src/middleware.ts). Remember `PUBLIC_PATHS` needs any new
  public page, and the matcher excludes `/api/*`.

**Invitations ship without email infrastructure.** The console generates a copyable invitation link; the
invitee's own sign-in email — the OTP or magic link — is sent by Stack. Given that the repo has no mail
capability at all today, a copy-link flow means we do not have to build one to ship tenancy. Server-sent
invitation mail is a later decision on its own merits, not a blocker.

## 8. Isolation — application scoping and Postgres RLS

Unchanged from roadmap §6, with one thing removed: there is no Java connection pool to also configure.

### How scope reaches Postgres

There are 210 `async_session()` call sites in `api/db/` but **exactly one engine**
([api/db/base_client.py:11](../api/db/base_client.py)). A SQLAlchemy Core `begin` event on that engine covers all
of them without touching one.

The hook writes four GUCs via `set_config(..., true)` — the function form of `SET LOCAL`, so
**transaction-scoped**. A plain `SET` here would leak one tenant's scope into the next pool checkout, which is
exactly the bug RLS exists to prevent.

Installed by **two appended lines** in [api/db/\_\_init\_\_.py](../api/db/__init__.py), a 3-line file — covering
routes, tasks, MCP and services alike, with no import cycle. This is the cheapest available seam.

**Fail-closed**: an unset ContextVar writes `scope_mode = 'none'`, which every policy denies. A code path that
forgets to enter scope returns zero rows loudly rather than everything silently.

`api/db/database.py` holds a second engine with **zero importers** — dead code, and the one way to get a
connection the hook does not cover. Delete it or document it.

### Policy predicate

```sql
CREATE POLICY tenant_isolation ON <table>
  USING      (app.scope_mode() = 'platform' OR organization_id = ANY (app.scope_org_ids()))
  WITH CHECK (app.scope_mode() = 'platform' OR organization_id = ANY (app.scope_org_ids()));
```

`app.scope_org_ids()` is `STABLE` returning `int[]`, reading `saas.org_node`. `STABLE` lets the planner evaluate
it once per statement, producing a small constant array; `organization_id = ANY (array)` is index-usable on the
existing `ix_*_organization_id` indexes, where a correlated `EXISTS` would be a per-row subplan on the hottest
tables in the system. It is *the same array* the application filter uses, so the two layers cannot disagree. A
vendor with 500 customers yields a 500-element array — fine; 50,000 would not be, and that is the documented
threshold for switching that branch to an indexed `EXISTS`.

`WITH CHECK` matters as much as `USING`: without it, a scoped session can *write* a row into another tenant.

### Roles

| Role | Owns tables | BYPASSRLS | Used by |
|---|---|:--:|---|
| `dograh_migrate` | **yes** | **yes** | Alembic only |
| `dograh_app` | no | no | FastAPI and ARQ workers |
| `dograh_system` | no | **yes** | an enumerated allowlist of fleet-wide jobs |
| `dograh_readonly` | no | no | analytics, on a replica |

**`FORCE ROW LEVEL SECURITY` on every policied table, without exception.** Plain `ENABLE` exempts the table
owner, and `DATABASE_URL` points at `postgres` — the owner — today, so an `ENABLE`-only deployment would silently
apply no policies while looking correct in `pg_policies`. `FORCE` is the guard against the most likely
operational mistake in this repo.

Fleet-wide jobs use a **separate role on a separate engine**, not a `scope_mode = 'system'` GUC: a GUC can be set
by anything that can execute SQL in the session, including through an injection in a `text()` query — and
`execute_raw_query` exists in [api/db/base_client.py](../api/db/base_client.py). A role-based bypass cannot be
forged from inside a session.

### Enforcement is configuration, not code

The migration always creates the policies, so schema is uniform everywhere. Whether they are *enforced* depends
entirely on which role the connection string names. Zero code branches, zero feature flags in query paths, and
the posture of any deployment is answerable by reading one env var. `DEPLOYMENT_MODE=oss` single-tenant installs
are unaffected.

---

# Part B — Development roadmap

Eleven phases, replacing roadmap Phases 1–12 and 15. Each names a falsifiable exit criterion.

**Standing rules for every phase.** `local` and `stack` auth keep working throughout. New endpoints follow the
`require_local_auth` pattern (router always mounted, gate at request time) so the OpenAPI spec and generated SDKs
do not vary by deployment. `bash scripts/lint.sh` and the full pytest suite — baseline **1892 passed** — stay
green. Run `scripts/generate_sdk.sh` **step 1 only**, per FORK.md.

## S0 — Documentation

This document. Mark the identity half of `tenancy-auth-roadmap.md` superseded; close `AUTH-PROVIDER.md` with the
self-hosted Stack decision. Add `api/db/__init__.py` and `api/alembic/env.py` to FORK.md's seam table.

**Exit:** decisions recorded; no code touched.

## S1 — Self-hosted Stack in the EU

Deploy Stack into EU infrastructure with its own Postgres. `docker-compose.yaml` service block on `app-network`
with an explicit `environment:` map (the repo uses no `env_file:` anywhere), plus a healthcheck. Entries in
**both** parallel arrays of `scripts/start_services_dev.sh`; `scripts/AGENTS.md` makes `start_services_dev.ps1`
parity a hard rule. Configure Stack's own SMTP.

**Pin the Stack SDK version.** [ui/src/app/impersonate/route.ts:166](../ui/src/app/impersonate/route.ts)
constructs the `hexclave-refresh-<projectId>--default` cookie name by hand and is coupled to Stack's internals.

**Self-hosting moves OTP-mail deliverability into our lap; it does not remove it.** An OTP mail that lands in
spam is a total login outage with no workaround, because there is no password to fall back to. Dedicated sending
domain, SPF + DKIM + DMARC, bounce and complaint handling, a transactional reputation pool, and monitoring on
delivery latency — an OTP that arrives in four minutes is a failed login.

**Exit:** magic-link and Google sign-in both work against the self-hosted instance; a test send reaches Gmail,
Outlook and a corporate Workspace inbox — **not** spam — with median delivery under 10 seconds.

## S2 — `AUTH_PROVIDER=failte` with JWKS

`api/saas/auth/depends_failte.py`, the three-line branch in `get_user`, JWKS caching with rate-limited `kid`
refetch, profile fetch only for new users, and no `selected_team_id` requirement. UI: add `'failte'` to the
provider union, a config branch, two optional `HealthResponse` fields, and the wrapper.

Fix two blocking pre-existing issues in passing (see §Pre-existing issues).

**Exit:** a full session — login, REST, WebSocket call, API key — runs with Stack's server API unreachable.
`local` and `stack` still work.

## S3 — Tenancy tree

The `saas` tables with every constraint from §2, plus the tenancy router and provisioning.

**Exit:** four operations are **impossible**, each proven by a failing-insert test — a user under vendor A
joining an org under vendor B; a platform admin holding a customer membership; a four-level tree; an `org_node`
whose `tenant_root_id` disagrees with its parent.

## S4 — Data migration

`saas_`-prefixed Alembic revisions. Create the platform node and the permanent house vendor **"Failte AI
Direct"**; attach every existing organization under it as `customer`; mark every existing membership `admin`.
That encodes the status quo honestly rather than guessing at demotions — demote deliberately afterwards, in the
product, with an audit trail. Self-serve signup provisioning points at the house vendor from here on, so there is
no such thing as a vendor-less org row.

**One destructive step needing a human-reviewed dry run:** `is_superuser` users become platform admins, and the
§2 constraints then forbid them holding customer memberships — those rows must be deleted. If a superuser
genuinely needs to operate inside a tenant, that is what impersonation is for.

**Exit:** the dry-run report is reviewed and signed off; the migration is reversible up to the deletion step. A
direct customer created after the migration is indistinguishable in shape from one created by a real vendor.

## S5 — Tenant context, log-only

`TenantContext`, the resolver, the capability module, and `require()` guards on new routes in **log-only mode** —
denials are logged, not enforced. Membership verification switched on.

**Exit:** one week of clean deny-logs in production. Canary tests (`api/tests/test_auth_depends.py`,
`api/tests/test_organization_bootstrap.py`) green.

## S6 — Enforce capabilities, ship consoles

Flip `require()` to enforcing. Platform and vendor consoles in `ui/src/saas/`; the org switcher replacing the
Stack team switcher; member management; role-gated routes in middleware.

**Exit:** a vendor admin provisions a customer org and invites its first admin, end to end, in the UI.

## S7 — Transitive `organization_id`

Add nullable column + index → application sets it on insert → `BEFORE INSERT` trigger derives it from the parent
when NULL → batched backfill by id range → **a later, separate deploy** sets `NOT NULL` → `BEFORE UPDATE` trigger
rejects changes, or a row can be walked across tenants. Backfill `workflows.organization_id` from
`user_id → users.selected_organization_id`.

**Schema → code → constraint, three deploys, never one.**

**Exit:** all five tables `NOT NULL` with zero orphans; the suite green.

## S8 — Application scope helper

The shared filter helper through the `db/` clients, translating the same scope descriptor the RLS policy will
use. Add `("saas","db")` to `INTERNAL_TOOLING_PREFIXES` in
[api/tests/test_db_layer_boundary.py](../api/tests/test_db_layer_boundary.py) — otherwise `api/saas/db/` fails
that guard for importing sqlalchemy.

**Exit:** every org-scoped query goes through the helper, asserted by a boundary test.

## S9 — RLS created, enforcement off

The `app` schema functions, four roles, grants, `ENABLE` + `FORCE`, policies, and the GUC hook. Production keeps
naming the bypass role, so nothing changes behaviourally.

Run **shadow mode**: sampled queries executed through both roles, row-count divergence logged. A divergence is
either a missing policy or an over-broad application filter — either is a finding.

**Exit:** shadow divergence silent for one week in staging *and* production.

## S10 — RLS enforced

Flip `DATABASE_URL` to the non-bypass role. Keep the bypass role available for a fast rollback.

**Exit:** a cross-tenant read returns zero rows in the RLS test suite; a cross-tenant write is rejected by
`WITH CHECK`.

## S11 — Impersonation, audit, and the commercial layer

Impersonation already exists and is Stack-native — wire the impersonator into the tenant context and every
written row. `audit_log` append-only **enforced by revoking UPDATE/DELETE from the app role**, not by convention
— otherwise the strongest thing we can tell an enterprise customer about impersonation is unenforceable. Customer
admins can see impersonations into their own org. Then billing rollup, quotas down the tree, white-label domains.

**Exit:** an impersonation session is fully reconstructable from the audit log, and the impersonated org's admin
can see it.

The tool-standard catalog and the Java `http_api` executor (roadmap Phases 13–14) are unaffected by this document
and can follow independently — neither ever needed Java for identity reasons.

---

## Ordering decisions worth defending

- **Stack before tenancy (S1–S2 before S3).** A working login on the target provider is independently valuable
  and exercises the whole Stack↔Python↔UI path on the simplest possible feature.
- **JWKS before the tree (S2 before S3).** Removing the `selected_team_id` requirement is a prerequisite for a
  vendor acting outside their own org, so it must land first regardless.
- **RLS after application scoping (S9–S10 after S8).** If RLS lands first, every missing application filter
  surfaces as a mysterious empty result and gets "fixed" by widening scope. Landing scoping first makes RLS a
  *confirmation* of an invariant we already hold, and shadow mode measures exactly that.

## Upstream delta — the whole cost

Per FORK.md, new files are free and every line in an upstream file is a conflict paid on every sync.

| File | Change | Lines |
|---|---|---|
| [api/services/auth/depends.py](../api/services/auth/depends.py) | 3-line `failte` branch in `get_user`; **zero for scope** | 3 |
| [api/db/models.py](../api/db/models.py) | `organization_id` on 5 transitive models. **Nothing on User/Organization/membership** | ~10 |
| [api/routes/main.py](../api/routes/main.py) | routers appended, 2 optional `HealthResponse` fields | 6 |
| [api/db/\_\_init\_\_.py](../api/db/__init__.py) | RLS hook install (**new seam**) | 2 |
| [api/alembic/env.py](../api/alembic/env.py) | import so autogenerate sees `api/saas/db/models.py` (**new seam**) | 1 |
| [api/tests/test_db_layer_boundary.py](../api/tests/test_db_layer_boundary.py) | allowlist `("saas","db")` | 1 |
| [ui/src/lib/auth/](../ui/src/lib/auth/) | `'failte'` in the provider union, config branch, wrapper wiring | ~15 |
| `ui/src/middleware.ts`, `OrgConfigContext.tsx`, `SidebarTeamSwitcher.tsx` | role gating, context source swap, switcher swap | ~60 |

Everything else is new files in `api/saas/` and `ui/src/saas/` — free.

Two entries are **new to FORK.md's seam table** and should be added deliberately: `api/db/__init__.py` and
`api/alembic/env.py`. Both are append-only two-line changes to short files, and both are load-bearing.

Against the roadmap's own delta, this design **removes** the `custom_tool.py` change (~15 lines) and the entire
`java/` tree from the identity path.

## Pre-existing issues found, to fix in passing

1. **PyJWT is not declared in `api/requirements.txt`** — it is present only transitively via `fastmcp` and
   `langfuse`, while [api/utils/auth.py](../api/utils/auth.py) imports it directly. A dependency bump elsewhere
   breaks auth. This becomes blocking in S2, which adds JWKS verification.
2. **`create_jwt_token` has no `typ` claim** ([api/utils/auth.py](../api/utils/auth.py)) — it mints
   `{sub, email, exp, iat}` with no purpose claim. Introducing a second token kind without one means one token
   kind would be accepted anywhere another is. Every token we mint should carry `typ`, and every verifier should
   assert the expected value.
3. **`create_user_with_email(name=...)` accepts `name` and never assigns it**
   ([api/db/user_client.py:208](../api/db/user_client.py)) — signup echoes a name it did not store.

## Open questions

Carried forward from the roadmap, still open:

- **Billing attribution** across the tree. Does a vendor get aggregated billing across their customers, and does
  the platform bill the vendor or the customer? Does a direct-billed customer still count toward the vendor's
  volume tier? Note the house vendor makes "direct customer" answerable in the same model rather than as an
  exception.
- **White-labelling.** Resolving a tenant from the `Host` header conflicts with `ui/src/middleware.ts`'s
  module-scoped, TTL-less provider cache. Needs its own bounded cache.
- **Quotas down the tree.** An effective-config resolver walking two hops up is easy; making MPS respect a
  vendor-level cap is not, and may not be possible without an MPS change.
- **Provisioning inversion.** `ensure_organization_bootstrapped` assumes `created_by` is a member and runs lazily
  on an authenticated request. A vendor-created customer org breaks both assumptions — until its first admin
  signs in, the org is never bootstrapped: no model configuration, no SIP. Make provisioning explicit at creation
  time via an ARQ task, keeping the lazy path only for self-serve signup.
- **There is no CD workflow for the Docker stack at all.** `docker-image.yml` only builds and pushes; deploys are
  operator-driven via `update_remote.sh` / `rolling_update.sh`. A self-hosted Stack service inherits that.

New, arising from this design:

- **Self-hosted Stack upgrade cadence and version pinning.** How far behind upstream Stack do we run, who watches
  their security advisories, and what breaks when the cookie-name or JWKS shape changes? The hand-constructed
  cookie name in `impersonate/route.ts` is the known coupling; there may be others.
- **Enterprise SSO/SAML and MFA.** Whether Stack's support is sufficient for the enterprise tier, or whether that
  reopens the provider question later. Better answered before the first enterprise deal than during it.
- **Whether server-sent invitation mail needs its own phase**, or the copy-link flow is sufficient indefinitely.
- **Verify Stack's Google account-linking behaviour** matches the `email_verified: true` rule. Without that
  check, anyone who can get Google to issue a token for an unverified address they typed can be linked into
  someone else's account.
