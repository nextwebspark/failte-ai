# Tenancy and RBAC design

> **Status: draft.** The hierarchy design below is settled in shape. Table-level specifics wait on the auth provider decision (`AUTH-PROVIDER.md`) — though see "Why this is not blocked" for why less depends on that than it looks.

## The hierarchy we need

Four levels, with the same admin/member pair recurring at each tenant level:

```
Platform (us)
└── super admin ......... sees everything, impersonates, provisions vendors
    │
    Vendor (reseller / partner)
    ├── vendor admin ..... manages their client workspaces, billing, branding
    └── vendor member .... operates within the vendor scope, cannot provision
        │
        Client workspace (the end customer, itself a company)
        ├── workspace admin ... manages members, agents, telephony, keys
        └── workspace member .. builds and runs agents
```

The recurring admin/member pair is the standard B2B2B shape: each level owns the level below it, and no level can see sideways into a sibling.

## What upstream already gives us

Dograh is genuinely multi-tenant today. This matters — it means we extend rather than retrofit.

| Concern | State in upstream |
|---|---|
| Tenant entity | `OrganizationModel` (`api/db/models.py`) with `provider_id`, config, usage cycles, API keys |
| Membership | `organization_users` association table (`user_id`, `organization_id`) — plus `users.selected_organization_id` for the active tenant |
| Resource scoping | **Already pervasive.** `organization_id` FK on workflows, folders, tools, campaigns, telephony configs and phone numbers, knowledge base docs, recordings, integrations, embed tokens, agent triggers, external credentials, webhook deliveries |
| Auth seam | `AUTH_PROVIDER` env selects `local` (email/password + JWT) or `stack` (Stack Auth). The UI discovers the provider at runtime from `/api/v1/health` — switching needs no rebuild |
| Request-time identity | `get_user` in `api/services/auth/depends.py`, single entry point for header auth, API-key auth and WebSocket auth |
| Org provisioning | `ensure_organization_bootstrapped` (`api/services/organization_bootstrap.py`), called on every authed request, self-limiting to one indexed read once provisioned |
| Impersonation | `POST /superuser/impersonate` (`api/routes/superuser.py`), already built |

### What is missing

Two things, and only two:

1. **Roles.** `organization_users` has no `role` column. The only role signal in the entire codebase is the boolean `users.is_superuser`, gated by `get_superuser`. There is no admin/member distinction *within* an organization.
2. **Hierarchy.** Organizations are flat. There is no vendor/reseller level and no parent-child relationship between organizations.

## Recommended model

**Extend `organizations` with a parent pointer and a type; add a role to the membership table.**

```
organizations
  + parent_organization_id  FK organizations.id, nullable
  + org_type                enum('platform', 'vendor', 'client')

organization_users
  + role                    enum('admin', 'member')
```

Why this over the alternatives:

- **Every existing FK and query keeps working untouched.** Dozens of tables carry `organization_id`; a client workspace is still just an organization. Nothing about workflow, campaign, telephony or knowledge-base scoping changes. Against a fork we must keep merging with upstream, blast radius is the deciding criterion.
- Subtree scoping (a vendor admin listing everything under them) is one recursive CTE, and the tree is shallow — three levels, so depth is bounded and the query is cheap.
- It composes forward. Generic `roles` / `permissions` / `grants` tables for per-vendor custom roles can be layered on later without redoing this.

Alternatives considered and rejected for now: a separate `vendors` table with `organizations.vendor_id` (explicit, but adds a second scoping dimension to every query, forever); full Zanzibar-style relation tuples (most flexible, disproportionate upfront cost — revisit if we adopt Ory Keto).

## Enforcement points

All of them are already single choke points, which is what makes this tractable.

**`api/services/auth/depends.py`** — layer a tenant-scoped dependency over `get_user` rather than rewriting it. It should resolve, per request: the acting user, the active organization, that user's role in it, and the set of organization ids they may reach (self + descendants). Three call paths must all end up carrying that context:

- Header auth (`local` JWT or Stack) — the main path.
- **API key auth** (`_handle_api_key_auth`) — note it *pins* `user.selected_organization_id` to the key's organization. Any scope resolution must respect that pin rather than recomputing from the user.
- **WebSocket auth** (`get_user_ws`) — delegates to `get_user`, so it inherits whatever we add, but must be verified explicitly since telephony rides on it.

**Route guards** — a `require_role(...)` dependency alongside the existing `get_superuser`. Follow that file's existing style: a FastAPI dependency raising `HTTPException(403)`, not middleware.

**Query-level isolation** — the risk is not the routes we write carefully, it is the one query someone forgets to scope. Decide between application-level scoping (a shared filter helper, cheap, relies on discipline) and Postgres row-level security (defence in depth, more moving parts). `api/db/filters.py` and the `db_client` layer are where a shared helper would live; `api/tests/test_db_layer_boundary.py` suggests upstream already enforces some layering discipline worth reading before choosing.

**Impersonation** — `/superuser/impersonate` exists but is Stack-specific (it mints a Stack session). Whatever provider we land on needs an equivalent, and it must be audit-logged: platform admin impersonating into a client workspace is the single most sensitive action in the system.

## Why this is not blocked on the auth provider

**No mainstream identity provider models a four-level hierarchy natively.** Clerk organizations are explicitly flat; so are WorkOS, Auth0 and Stack Auth. Every one of them expects hierarchy to live in your own database.

So the hierarchy tables above are provider-independent. What the provider decides is narrower: how users authenticate, how sessions and tokens work, how invitations and SSO are handled, and how much of the membership state we mirror versus own. The design here holds under any of the candidates.

## Open questions for the implementation session

- **Isolation guarantee.** Application-level filters versus Postgres RLS. What do we need to be able to tell an enterprise client, and what does an EU compliance posture demand?
- **Cross-vendor visibility.** Can a user belong to organizations under two different vendors? The current `organization_users` M2M permits it structurally. Probably should not be allowed, and that needs to be an enforced constraint rather than a convention.
- **White-labelling.** Do vendors get their own domains and branding? That decision reaches into the UI, the embed widget, and email templates — better known early than retrofitted.
- **Billing attribution.** Usage is tracked per organization today (`organization_usage_cycles`, `api/services/workflow_run_billing.py`). Does a vendor get aggregated billing across their clients, and does the platform bill the vendor or the client?
- **Provisioning flow.** `ensure_organization_bootstrapped` currently assumes a self-serve signup creating its own org. Vendor-created client workspaces invert that — the creator is not the first member.
- **Quotas down the tree.** Can a vendor cap what each of their clients consumes, or is that platform-level only?
