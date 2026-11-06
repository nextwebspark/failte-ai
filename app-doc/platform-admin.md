# Platform admin (founder tools)

The platform admin area is at **`/superadmin`** in the app. Only users with
`users.is_superuser = true` can use it. The API checks this on every request
(`require_platform_admin`). If anyone else opens the area, they only see "This
area is for platform admins only".

The area is not in any workspace's nav. You reach it by URL. After sign-in, a
platform admin also lands on it (see `getRedirectUrl` in `ui/src/lib/utils.ts`).
Every change made in it is written to the audit log.

## Making the first platform admin

The area can't grant platform admin until there is one platform admin. For the
first one, set the flag in the database directly:

```sql
-- Find the account (it must have signed in at least once).
SELECT id, email, is_superuser FROM users WHERE lower(email) = lower('founder@example.com');

-- Make it a platform admin.
UPDATE users SET is_superuser = true WHERE lower(email) = lower('founder@example.com');
```

With the Docker Compose deployment, you can run this from the host:

```bash
docker compose exec postgres psql -U postgres -d postgres \
  -c "UPDATE users SET is_superuser = true WHERE lower(email) = lower('founder@example.com');"
```

The change takes effect on that user's next request; they don't need to sign out.
After that, use **Users > Make admin** for everyone else. Grants made in the app
are audited; the first SQL grant is not.

The API refuses two changes:

- removing your own platform admin access (ask another admin);
- removing the last platform admin.

## Screens

| Tab | What it does |
|---|---|
| **Overview** | Users and sign-ups (7 days, 30 days, this month), and workspaces. Active workspaces are those that made a call in the last 7 or 30 days. Also shows calls (7 days, this month) and minutes this month. Revenue, estimated provider cost and estimated margin for this month come from the same margins service as `GET /superuser/billing/margins`. Revenue appears only with `BILLING_PROVIDER=stripe`. "Calls" means voice runs of every kind, browser tests included. Text chats are not counted. Months are UTC. |
| **Health** | Configuration checks on the API server that answered: `EMAIL_PROVIDER` none, `BILLING_PROVIDER` none (or Stripe keys missing), `PUBLIC_BASE_URL` unset or pointing at localhost, `TOOLS_*` missing, Sentry off, and the default `OSS_JWT_SECRET` with local sign-in. Also shows failed calls in the last 24 hours (`call_status` failed, error, pipeline_error or unexpected_error). Stuck runs are runs from the last 24 hours that are still `initialized` or `running` more than an hour after they started (the newest 20 are listed). Integration connections in `error` are read from the tools service, for up to 200 workspaces that have an integration installed. |
| **Features** | Turns Campaigns and Skills on or off for every workspace, or back to the default in code (off). Lists the per-workspace overrides. |
| **Organisations** | Every workspace, newest first. Search by name, id or a member's email. Columns: status, members, plan, balance, per-minute rate, credit limit, calls-at-once limit, created date and last call. The detail page shows members and their roles, the 20 most recent calls and the newest 50 ledger entries. It also has these actions: plan and per-minute rate and credit limit, add or remove credit with a reason, the concurrent-call limit, and per-workspace feature overrides. |
| **Users** | Every account, newest first. Search by email, name or id, or show platform admins only. Shows each user's workspaces and roles, and whether their email is verified. Last sign-in is not recorded by the app, so it isn't shown. Actions: Make admin or Revoke admin, and Impersonate (see below). |
| **Audit log** | Every change made in this area: who made it, when, what it was, the workspace or user it applied to, and before and after values. You can filter it by kind of change, or by workspace from a workspace's page. |
| **All runs** | The existing cross-workspace run list. |

### Feature switches

- **Where they're stored:** in the `platform_feature_flags` table. One row holds
  the platform-wide value. Optional rows hold per-workspace overrides. With no row,
  the default in code applies (`api/services/platform_admin/features.py`, and the
  same values in `ui/src/config/features.ts`).
- **Who can read them:**
  - `GET /api/v1/features`: the effective values for the caller's selected
    workspace. Any signed-in user can call it.
  - `GET /api/v1/features/public`: no sign-in needed. It only says whether each
    area is on for at least one workspace.
- **How the app uses them:**
  - **Middleware** reads `/features/public`. It sends an area's pages to Overview
    only when the area is off everywhere. The answer is cached for 30 seconds per
    UI worker. If the backend can't answer, the defaults apply (off).
  - **The app shell** reads `/features` after sign-in, and again when the user
    switches workspace. It applies the workspace's own value to the nav, the
    pages (they redirect to Overview) and the pickers.
  - **If the read fails,** the defaults apply.
- **What they don't change:** the API, saved data and running calls. An open
  page picks up a change on its next full load.

### Billing actions

The billing actions use the existing `/superuser/billing/*` endpoints, so they
only work with `BILLING_PROVIDER=stripe`. On other deployments, the workspace
page says billing is off.

Changing the plan or the rates of a workspace that has no billing account yet
creates one. That also gives it the usual welcome credit, as before.

### Concurrent-call limit

The limit is stored as the workspace's `CONCURRENT_CALL_LIMIT` configuration,
and is read on every call. "Use the default" removes it, so the workspace goes
back to `DEFAULT_ORG_CONCURRENCY_LIMIT`.

### Impersonation

- **Stack Auth sign-in** (`AUTH_PROVIDER=stack`): **Impersonate** opens the user's
  session in a new tab, as before. Each session that starts is now written to the
  audit log.
- **Local sign-in** (`AUTH_PROVIDER=local`, the default): impersonation is **not
  available**. The API answers `501` with "Impersonation is not available with
  local sign-in", and the Users screen disables the button and shows that message.

Local sessions are plain signed tokens with no server-side record. A safe local
version would need short-lived, marked impersonation tokens, a way to return to
your own session, and a visible banner while impersonating. That was left out of
this change on purpose.

## Audit log

The audit log is the `platform_admin_audit_log` table. It records only ids
(actor, workspace, target user), the action, and a JSON `details`. Names and
emails are joined in when the log is shown, so deleting a user or erasing a
workspace leaves no personal data in the log. The exception is text an admin
typed, such as the reason given for a credit change.

| Action | Recorded when |
|---|---|
| `feature.platform_set` / `feature.organization_set` | a feature switch changes (before and after values) |
| `billing.terms_updated` | a workspace's plan, per-minute rate or credit limit changes (before and after values) |
| `billing.balance_adjusted` | credit is added or removed (amount, ledger type, reason, ledger entry) |
| `organization.concurrency_limit_set` | the concurrent-call limit changes |
| `user.platform_admin_granted` / `user.platform_admin_revoked` | platform admin access changes |
| `user.impersonation_started` | a Stack Auth impersonation session is created |

Changes that do nothing (setting a value it already has) are not recorded.

## API

Every route is under `/api/v1/superuser/admin` and needs a platform admin.
They're left out of the OpenAPI schema, like the other superuser billing routes,
so they aren't in the published API reference.

| Method and path | What it does |
|---|---|
| `GET /overview` | Overview numbers |
| `GET /health` | Health checks |
| `GET /features` | List the feature switches |
| `PUT /features/{feature}` | Set a platform-wide switch: `{"enabled": true\|false\|null}` |
| `PUT /features/{feature}/organizations/{id}` | Set a per-workspace override (same body) |
| `GET /organizations?search=&page=&limit=` | List workspaces |
| `GET /organizations/{id}` | One workspace |
| `PUT /organizations/{id}/concurrency-limit` | Set the concurrent-call limit: `{"limit": 1..1000 \| null}` |
| `GET /users?search=&platform_admins_only=&page=&limit=` | List users |
| `PUT /users/{id}/platform-admin` | Grant or revoke: `{"is_platform_admin": true\|false}` |
| `GET /audit-log?organization_id=&action=&page=&limit=` | The audit log (`action` is a prefix, e.g. `billing.`) |
