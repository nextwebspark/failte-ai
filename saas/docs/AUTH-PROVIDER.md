# Auth provider evaluation

> **Status: open.** No decision made. This records what we know so the next session starts from evidence rather than from scratch.

## Constraints

1. **EU data residency.** Identity data must reside in the EU. This is the primary filter and it rules out any provider whose control plane is US-hosted by default with no EU option.
2. **Four-level hierarchy**: platform → vendor → client workspace → member (see `RBAC.md`).
3. **Must fit the existing seam.** Upstream's `AUTH_PROVIDER` env var already selects between `local` and `stack`, with the UI discovering the active provider at runtime from `/api/v1/health`. A third provider should drop in beside them, not replace the mechanism.

## The finding that simplifies everything

**No mainstream identity provider models a multi-level organization hierarchy natively.**

- **Clerk**: organizations are flat. Their own documentation describes a single-level model with no parent-child relationship; the documented workaround is organization metadata plus your own tables.
- **WorkOS, Auth0, Stack Auth**: same — flat organizations.

So the vendor → client hierarchy lives in our Postgres **regardless of which provider we choose**. That decouples the tenancy design from this decision entirely. What the provider actually decides is narrower:

- Authentication methods (password, social, SSO/SAML, MFA)
- Session and token issuance, and what claims we can put in a token
- Invitation and onboarding flows
- Enterprise features: SCIM provisioning, directory sync
- Impersonation support (we need it — see `RBAC.md`)
- Operational burden if self-hosted

## Clerk, specifically

Raised as a candidate. Findings, for the record:

- Organizations are flat — no nesting (see above).
- **10 custom organization roles per application instance**; beyond that requires contacting support. Roles and permissions are defined once at the *application* level and apply across all organizations, which is a poor fit for per-vendor custom roles.
- Custom roles in production require the **B2B Authentication add-on**.
- System permissions are **not** included in session claims — server-side authorization checks need custom permissions defined explicitly.
- Pricing is per **Monthly Retained Organization**. Under a four-level tree, both vendors and their client workspaces are organizations, so the org count — and the bill — grows with every client every vendor signs.
- Hosting is Clerk's cloud. EU residency needs verification against constraint 1 before Clerk can be considered at all.

Net: workable but expensive under our tree shape, and the EU constraint is unresolved. Not recommended without a specific reason to prefer it.

## Self-hostable candidates

All deployable in EU infrastructure, which is the point.

| Candidate | Notes |
|---|---|
| **Stack Auth** | Already integrated upstream (`api/services/auth/stack_auth.py`, `ui/src/lib/auth/providers/StackProviderWrapper.tsx`) and open source / self-hostable. Self-hosting it in the EU is potentially the cheapest path — the integration code already exists and includes impersonation. Verify the self-hosted deployment story and maturity. |
| **Ory Kratos + Keto** | Kratos handles identity; **Keto is a Zanzibar-style ReBAC engine** and is the strongest fit for hierarchical permission inheritance — the vendor→client→member relation chain is precisely what it models. Highest ceiling, highest operational cost. |
| **Zitadel** | Multi-tenant by design with organizations and projects, self-hostable, EU-based company. Closest thing to native B2B2B among the candidates. |
| **Keycloak** | The default enterprise answer. Realms, groups, fine-grained authorization, SAML/OIDC/SCIM. Heavy, dated DX, but battle-tested and nobody gets fired for it. |
| **Logto** | Modern, lighter than Keycloak, has an organizations feature. Younger project. |
| **Authentik** | Strong on SSO/directory integration, more IdP than B2B SaaS auth backend. |
| **SuperTokens** | Self-hostable, good DX, multi-tenancy support. Thinner on enterprise SSO/SCIM. |

## Also on the table: build on the existing local provider

Upstream's `local` provider is already a working email/password + JWT implementation (`api/routes/auth.py`, `api/utils/auth.py`, bcrypt). Extending it to carry tenant and role claims means no external dependency, no per-seat cost, no residency question at all, and total control.

The cost is everything an IdP gives you for free: invitations, password reset, MFA, social login, SSO/SAML, SCIM. For enterprise clients, SSO is usually non-negotiable — so the realistic version of this option is "own the core, add an IdP later for enterprise tiers", which risks paying for the migration twice.

## Evaluation criteria for the next session

Score each candidate on:

1. **EU residency** — self-hosted in our own EU infrastructure, or a provider EU region with contractual guarantees.
2. **Effort to integrate** — how cleanly it drops into the `AUTH_PROVIDER` seam. Stack Auth starts from a large head start here.
3. **Enterprise readiness** — SSO/SAML, SCIM, MFA, audit logs.
4. **Invitation flows** — vendor invites client admin, client admin invites members. Multi-level invitations are where flat-org providers get awkward.
5. **Impersonation** — platform admin into any tenant, audit-logged. Upstream's existing `/superuser/impersonate` is Stack-specific and needs an equivalent.
6. **Operational burden** — who runs it, patches it, and is paged when it breaks.
7. **Cost at scale** — model it against the tree: N vendors × M clients × K members, not flat MAU.

## Recommendation for how to decide

Prototype against the seam, do not decide on paper. The `AUTH_PROVIDER` abstraction means a candidate can be trialled as a third provider module without disturbing `local` or `stack`. Two serious contenders (likely self-hosted Stack Auth and Zitadel, with Ory Keto as the wildcard for permissions specifically) evaluated end-to-end against a real four-level tree will settle this faster than any comparison table.
