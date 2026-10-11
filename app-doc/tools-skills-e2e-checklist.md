# Tools service, integrations and skills: manual E2E checklist

This checklist verifies the epic "Fallcha tools service, integration catalog and agent skills"
(sub-issues 1–11) against **real Google** and **chmarine.com**. Automated tests mock Google and
the crawler, so the only proof that the real APIs behave as assumed is this run.

- Tick each box and note anything unexpected.
- Each step says what to do (**Do**) and what you should see (**Expect**).
- Steps marked **(never tested for real)** exercise code that has only run against fakes. Watch
  them closely.

Use a **throwaway** Google account and calendar, and a copy of any real spreadsheet. Some steps
book and cancel events and append rows.

---

## 0. Prerequisites

- [ ] A Google Cloud project you control, with the **Google Calendar API** and the **Google
  Sheets API** enabled.
- [ ] A test Google account (for OAuth), plus a test calendar and a test spreadsheet owned by
  it.
- [ ] Docker, the repo's `venv`, and `tools/.venv`. To create `tools/.venv`:
  `uv venv tools/.venv --python 3.13 && VIRTUAL_ENV=tools/.venv uv pip install -e 'tools[dev]'`.
- [ ] Note the time. Some checks read logs "since the start of the run".

## 1. Environment

The usual setup runs on the host: the API on 8001, the UI on 3000 and the tools service on
8010. The datastores run in Docker on 5433/6380 (`saas/dev`).

The `psql` commands below connect to that Postgres as `postgres` / `postgres`. Export
`PGPASSWORD=postgres` first, or psql prompts for it. Use the value from `api/.env`
`DATABASE_URL` if you changed it.

- [ ] **Do:** `bash saas/dev/bootstrap-env.sh`.
  - **Expect:** `api/.env` gains `CREDENTIALS_ENCRYPTION_KEYS`, `TOOLS_INTERNAL_SECRET` and
    `TOOLS_SERVICE_URL=http://localhost:8010`.
  - **Expect:** `tools/.env` exists with `TOOLS_ENCRYPTION_KEYS` and the **same**
    `TOOLS_INTERNAL_SECRET`.
  - **Expect:** both files are `-rw-------` (`ls -l api/.env tools/.env`).
- [ ] **Bootstrap is idempotent.**
  1. Run `shasum api/.env tools/.env > /tmp/env.sha`.
  2. Run `bash saas/dev/bootstrap-env.sh` again.
  3. Run `shasum -c /tmp/env.sha`.
  - **Expect:** the second run prints no `~ set` lines.
  - **Expect:** both files are reported `OK`. Existing values are never replaced.
  - **Expect:** blanking `TOOLS_INTERNAL_SECRET=` in `tools/.env` and re-running refills it
    with the api's value.
- [ ] **Do:** compare the two secrets with
  `grep -h ^TOOLS_INTERNAL_SECRET api/.env tools/.env | uniq | wc -l`.
  - **Expect:** `1`.
- [ ] **Do:** check the OAuth URLs in `tools/.env`.
  - **Expect:** `TOOLS_PUBLIC_BASE_URL=http://localhost:8010`.
  - **Expect:** `TOOLS_UI_RETURN_URL` names the UI's real port, e.g.
    `http://localhost:3000/integrations`.

## 2. Bring the stack up

- [ ] **Do:** `docker compose -f docker-compose-local.yaml -f saas/dev/docker-compose-local.override.yaml up -d`.
  - **Expect:** postgres, redis and minio are healthy.
- [ ] **Do:** start the tools service:
  `cd tools && set -a && source .env && set +a && .venv/bin/alembic upgrade head && .venv/bin/uvicorn fallcha_tools.app:create_app --factory --port 8010`.
  - **Expect:** migrations reach head.
  - **Expect:** `curl -s localhost:8010/health` is OK.
- [ ] **Do:** start the API and UI as in `docs/contribution/setup.mdx`.
  - **Expect:** no `CREDENTIALS_ENCRYPTION_KEYS is not set` warning in the API log.
  - **Expect:** no skill seed sync error in the API log.
- [ ] **Do:** log in as an Admin and open **Integrations**.
  - **Expect:** three cards: Google Calendar, Google Sheets and Website product catalogue.
  - **Expect:** no "Integrations aren't configured on this server" banner.
- [ ] **Do:** stop the tools service and reload the page.
  - **Expect:** an error banner, and the rest of the app still works.
  - Start the service again afterwards.

*Compose variant (optional):* `scripts/setup_local.sh` writes the three secrets into `.env`,
and `docker compose up` runs `fallcha-tools` on the internal network. OAuth needs a public
callback, so test OAuth with the host setup above. On a remote install, use
`PUBLIC_BASE_URL/oauth/...`.

## 3. Google OAuth client

- [ ] **Do:** in Google Cloud, configure the OAuth consent screen. Choose **External** in
  testing, and add the test account as a test user.
- [ ] **Do:** create an **OAuth client ID** of type **Web application** with these authorized
  redirect URIs:
  - `http://localhost:8010/oauth/google-calendar/callback`
  - `http://localhost:8010/oauth/google-sheets/callback`

  (Remote: `https://<host>/oauth/<provider>/callback`.)
- [ ] **Do:** create a **service account** and download a JSON key. Share the test calendar
  with its email (*Make changes to events*), and the test spreadsheet (*Editor*).

## 4. Google Calendar via service account

- [ ] **Do:** Calendar → **Connect** → *Service account key* → upload the JSON.
  - **Expect:** "Key for <sa-email>".
  - **Expect:** after Connect, the settings dialog opens.
- [ ] **Do:** set:
  - `calendar_id` = the test calendar's id;
  - `timezone` = `Europe/Dublin`;
  - `event_summary_prefix` = `Voiptel call`.

  Then save and click **Test**.
  - **Expect:** a success toast.
  - **Expect:** the card reads "Connected as <sa-email> · Service account key".
- [ ] **Do:** check that the agent tool was created. Open **Tools**.
  - **Expect:** an MCP tool "Google Calendar" whose discovered functions are
    `check_appointment_availability`, `book_appointment` and `cancel_appointment`.
- [ ] **Do:** check that secrets are encrypted at rest:
  `psql -h localhost -p 5433 -U postgres -c "select provider, status, left(secret_enc, 6) from fallcha_tools.connections"`.
  - **Expect:** `gAAAAA` (a Fernet token), never JSON.
- [ ] **Do:** run
  `select credential_data from external_credentials where name like 'Google Calendar integration%'`.
  - **Expect:** `{"_enc": "v1", "ct": "..."}`, not a visible token.

## 5. Google Calendar via OAuth

- [ ] **Do:** Calendar → **Add another** → *Sign in with your account* → **Add a new OAuth
  client…**.
  - **Expect:** the redirect URI shown is exactly
    `http://localhost:8010/oauth/google-calendar/callback`.
- [ ] **Do:** paste the client ID and secret, then **Save and sign in**. Approve as the test
  user.
  - **Expect:** Google's screen lists only Calendar events/read-only and email. There is no
    full-calendar scope.
  - **Expect:** you are back on `/integrations?integration_result=success...`.
  - **Expect:** the connection is "Connected as <test-user-email> · Sign in with your account".
  - **Expect:** a second "Google Calendar" MCP tool exists.
- [ ] **Do:** check that logs hold no secrets. Search the tools service log for the callback.
  - **Expect:** `/oauth/google-calendar/callback?<redacted>`.
  - **Expect:** no `code=` or `state=` anywhere.
- [ ] **Negative: untick a scope.** Repeat the sign-in and untick a Calendar permission.
  - **Expect:** "The connection wasn't completed" (`scopes_missing`), and no new connection.
- [ ] **Negative: other browser.** Copy the Google authorization URL from the browser's
  network tab. Open it in a private window and finish consent there.
  - **Expect:** the private window cannot confirm the connection. The connection stays out of
    the list and expires after 10 minutes.

## 6. Google Sheets with a reused service account

- [ ] **Do:** Sheets → **Connect** → *Service account key*.
  - **Expect:** "Use the same service account (<sa-email>)" is preselected.
- [ ] **Do:** connect, then set:
  - `spreadsheet_id` (paste the full URL);
  - `orders_tab` = a tab with the shim's order headers.

  Click **Test**.
  - **Expect:** success.
- [ ] **Do:** compare the stored keys:
  `select provider, auth_mode, secret_enc <> '' from fallcha_tools.connections where auth_mode='service_account'`.
  - **Expect:** two rows, no upload the second time. The key was copied on the server.
- [ ] *(Optional)* Connect Sheets with OAuth using the **same** client.
  - **Expect:** the client is offered.
  - **Expect:** "Continue as <email>".
  - **Expect:** it works only once `.../google-sheets/callback` is registered on the client.
    Remove it from the client first to see the Google `redirect_uri_mismatch` error.

## 7. Website catalogue (chmarine.com)

- [ ] **Do:** Website product catalogue → **Connect** → `site_url` = `https://www.chmarine.com`.
  - **Expect:** "Importing products in the background", then "Syncing products…".
- [ ] **Do:** wait for the sync to finish. It takes tens of minutes, at roughly one request per
  second.
  - **Expect:** "N products · last synced …". N is in the hundreds or more, capped at 2000.
  - **Expect:** any `note` is sensible ("stopped at 2000 pages", "k page(s) could not be
    loaded").
- [ ] **Do:** click **Sync now** twice quickly.
  - **Expect:** the second click is refused while one sync runs (409).
- [ ] **Do:** check politeness in the tools log.
  - **Expect:** requests carry the `FallchaCatalogueBot/1.0` user agent.
  - **Expect:** no paths that `robots.txt` disallows.

## 8. Attach to a workflow and place web calls

- [ ] **Do:** in a test workflow's agent node, open the tools and go to **MCP**. Tick:
  - Calendar (service account): `check_appointment_availability`, `book_appointment`,
    `cancel_appointment`;
  - Sheets: `look_up_order`;
  - Catalogue: `search_products`, `product_detail`.

  Mention them in the prompt. Save.
- [ ] **Do:** start a **web call** from the workflow editor. Ask for "an appointment tomorrow
  morning".
  - **Expect:** the agent offers real free slots (check against the calendar).
- [ ] **Do:** book one, giving a name and phone.
  - **Expect:** an event appears in Google Calendar titled `Voiptel call …` at that time.
  - **Expect:** the run's tool log shows `book_appointment` succeeded.
- [ ] **Do:** in the same call, ask to cancel it.
  - **Expect:** the event is cancelled in Google Calendar.
- [ ] **Restore a cancelled event (never tested for real).** In a new call, book **the same
  slot with the same name and phone** as the cancelled booking. The deterministic event id
  collides with the cancelled event, so the service re-confirms it instead of inserting.
  - **Expect:** the booking succeeds.
  - **Expect:** the event is back in Google Calendar, confirmed, with the **same event id** as
    before. Check with the Calendar API Explorer `events.get`.
  - **Expect:** no duplicate event.
- [ ] **Do:** try to cancel an event created by hand in Google Calendar (give the agent its id).
  - **Expect:** "not found". Only events this connection booked can be cancelled.
- [ ] **Do:** ask for an order lookup with a real row's name and Eircode, then with a wrong
  Eircode.
  - **Expect:** the order status is read out for the real row.
  - **Expect:** the wrong Eircode gets the same generic miss sentence.
- [ ] **Do:** ask "do you have anchors for a small boat?", then for details of one product.
  - **Expect:** spoken prices ("twenty-nine euro ninety-five") and stock phrases.
- [ ] **Do:** repeat one booking on the **OAuth** Calendar connection.
  - **Expect:** an event appears in the test user's calendar (`primary` by default).

## 9. Token refresh (OAuth)

- [ ] **Do:** force expiry:
  `update fallcha_tools.connections set expires_at = now() - interval '1 minute' where auth_mode='oauth2' and provider='google-calendar' and status='active'`.
  Note `left(access_token_enc, 20)` first.
- [ ] **Do:** in a web call, ask for availability on the OAuth calendar.
  - **Expect:** a normal answer, with no user action.
  - **Expect:** `expires_at` is about 1 hour ahead and `access_token_enc` changed.
  - **Expect:** exactly one refresh in the tools log.
- [ ] *(Optional, single flight)* Expire it again and fire two availability calls at once, for
  example two browser tabs.
  - **Expect:** one refresh in the log.

## 10. Revoke and reconnect

- [ ] **Do:** at <https://myaccount.google.com/permissions>, remove the OAuth app's access for
  the test user. Then force expiry as in §9 and ask for availability.
  - **Expect:** the agent says the calendar is unavailable.
  - **Expect:** on Integrations, the connection shows **Needs attention**: "Access was revoked
    or expired in the Google account. Reconnect to restore it."
  - **Expect:** in the DB, `status='error'`, `error_code='grant_revoked'`, and tokens null.
- [ ] **Do:** ask again in a call.
  - **Expect:** the same error, and **no** request to Google in the log.
- [ ] **Do:** click **Reconnect** and sign in again.
  - **Expect:** a new connection and a new "Google Calendar" tool.
  - **Expect:** the "Remove the old connection?" prompt.
- [ ] **Do:** re-select the new tool's functions on the node, then **Remove old connection**.
  - **Expect:** the old tool is archived and its credential deleted.
  - **Expect:** the old key is refused (a call through the old tool fails cleanly).
  - **Expect:** a booking works through the new tool.

## 11. Credential encryption: enable and rotate

- [ ] **Enable on existing plaintext.** On a DB with plaintext credentials, start the API once
  without `CREDENTIALS_ENCRYPTION_KEYS`.
  - **Expect:** a startup warning.

  Set a key and restart. On this database the encryption migration has **already run**
  without a key, so it will not seal the existing rows. Seal them once:
  1. `python -m scripts.reencrypt_credentials --dry-run`
  2. `python -m scripts.reencrypt_credentials`

  In Docker, run both with `docker compose exec api`.
  - **Expect:** before the script,
    `select count(*) from external_credentials where credential_data::jsonb ? '_enc'` is
    lower than the total. After it, the two counts are equal.
  - **Expect:** a second run of the script reports `encrypted=0 failed=0`.
  - **Expect:** existing HTTP API tools still authenticate in a call.
- [ ] **Rotate.**
  1. Generate a new key and set `CREDENTIALS_ENCRYPTION_KEYS=<new>,<old>`. Restart.
  2. Run `python -m scripts.reencrypt_credentials --dry-run`, then without `--dry-run`.
  3. Set `CREDENTIALS_ENCRYPTION_KEYS=<new>`. Restart.

  - **Expect:** the script exits 0.
  - **Expect:** the API starts.
  - **Expect:** a call using an integration and an HTTP API tool both work.
- [ ] **Negative: wrong key.** Set only an unrelated key and restart.
  - **Expect:** the API refuses to start ("cannot decrypt an existing credential").
  - Restore the key afterwards.
- [ ] **Negative: non-OSS mode.** Set `DEPLOYMENT_MODE=saas` with no keys.
  - **Expect:** the API refuses to start.

## 12. Skills

- [ ] **Library seeds.** Open **Skills → Library**.
  - **Expect:** `appointment-booking` and `returns-policy`, at v1.
  - **Expect:** as a superuser, **Sync seeds** reports nothing changed.
- [ ] **Copy.** **Add to workspace** on `returns-policy`.
  - **Expect:** it is in **My skills** as "From library v1".
  - **Expect:** adding it again asks for another name and suggests `returns-policy-2`.
- [ ] **Edit.** Change one sentence of the copy and save.
  - **Expect:** the card shows **Modified**.
  - **Expect:** renaming alone would not set Modified (check on the second copy).
- [ ] **Update flow.** As a superuser, edit the library `returns-policy` and **Publish**.
  - **Expect:** v2.
  - **Expect:** both copies show **Update available**.
  - **Expect:** the unmodified copy updates with **Apply update**.
  - **Expect:** the modified copy needs **Replace my edits**. The diff shows your sentence
    against v2.
  - **Expect:** after the update, the name and allowed tools are kept.
- [ ] **Import/export.**
  1. Export a skill.
  2. Remove the `name` line from the frontmatter of the exported `SKILL.md`, re-zip it and
     import it.
     - **Expect:** a clear validation error.
  3. Import the untouched zip as a new name (edit `name`), with `allowed-tools: Read Bash`.
     - **Expect:** an "Imported …" dialog listing the dropped entries.
     - **Expect:** the skill shows "No other tools while loaded".
- [ ] **Run a call.** Leave the agent node's Skills at **All skills (default)**. In a web call,
  ask about returning a faulty item.
  - **Expect:** the agent calls `load_skill("returns-policy")` (and `read_skill_file` for
    `references/returns-policy.md`) before answering, and follows the steps.
  - **Expect:** the run page shows **Skills used** with "Loaded … in <node>".
  - **Expect:** the run's gathered context holds `skills_loaded` with `via: "load_skill"`.
  - **Expect:** asking an unrelated question does **not** load the skill.
- [ ] **Allowed tools.** Give a skill **Only selected tools** = the Calendar MCP tool. Load it
  in a call, then ask for a product search.
  - **Expect:** the catalogue call is refused with a message naming the allowed tools.
  - **Expect:** transfer and end call still work.
  - **Expect:** moving to another node lifts the restriction.
- [ ] **Preload.** Set the node's **Preloaded Skills** to `returns-policy` and call.
  - **Expect:** no `load_skill` call.
  - **Expect:** **Skills used** shows "Preloaded".
- [ ] **Per-node opt-out.** Set the node's Skills to **None**, with no preloads.
  - **Expect:** no "Available skills" block in the prompt (Langfuse trace or LLM log).
  - **Expect:** no `load_skill` function.
- [ ] **Workflow switch.** Workflow Settings → turn **Enable Skills** off.
  - **Expect:** no index, functions or preloads on any node.
  - **Expect:** no `skills_loaded` entries.
  - Turn it back on afterwards.
- [ ] **RBAC.** As a **Client** (viewer):
  - **Expect:** Skills is read-only ("You can view skills…").
  - **Expect:** Integrations is not in the menu.

## 13. Remote nginx route (when a remote stack is available)

Set `W='%{http_code} %{redirect_url}\n'` first. Every probe uses a GET with
`curl -s -o /dev/null --path-as-is -w "$W"`.

- [ ] **Do:** probe `"https://<host>/oauth/google-calendar/callback?code=x&state=y"`.
  - **Expect:** `302 https://<host>/integrations?integration_result=error&reason=invalid_state`.
- [ ] **Do:** probe `https://<host>/oauth/anything`.
  - **Expect:** `404` from the UI, not the tools service.
- [ ] **Path probes.** Probe each of these:
  - `https://<host>/oauth/x/../google-calendar/callback?state=y`
  - `https://<host>/oauth/google-calendar/%2e%2e/callback`
  - `https://<host>/oauth/%2e%2e%2finternal%2fcatalog/callback`
  - `https://<host>/oauth/..%2f..%2finternal/callback`
  - `https://<host>/internal/../oauth/google-calendar/callback?state=y`

  - **Expect:** the first and last probes give the same `302 ...reason=invalid_state`.
    nginx normalised them to the callback and forwarded the clean path.
  - **Expect:** the others give `404` (UI) or `400` (nginx), never a tools-service JSON body
    and never anything under `/internal`.
- [ ] **Do:** confirm the service itself refuses traversal with
the following (the api image has no curl):

  ```bash
  docker compose exec api python -c "import http.client as h; c=h.HTTPConnection('fallcha-tools', 8000); c.request('GET', '/oauth/x%2f..%2finternal/callback'); print(c.getresponse().status)"
  ```
  - **Expect:** `400`.
- [ ] **Do:** `curl -s -X POST -o /dev/null -w '%{http_code}' https://<host>/oauth/google-calendar/callback`.
  - **Expect:** 403.
- [ ] **Do:** `docker compose logs nginx | grep oauth`.
  - **Expect:** request lines without `?code=`.

## 14. GCP cutover (when the VMs are back)

Follow `deploy/gcp/README.md` → "Tools service cutover". These are the checks that must
pass **before** the old sidecars are stopped.

- [ ] **Do:** `./deploy/gcp/configure-env.sh`.
  - **Expect:** it finishes and writes `deploy/gcp/secrets/tools.env` with mode 600.
  - **Expect:** it stops with an error if `dograh-tools-internal-secret` or
    `dograh-tools-encryption-keys` is missing.
- [ ] **Do:** run `docker compose exec api python -m scripts.reencrypt_credentials` once after
  setting `CREDENTIALS_ENCRYPTION_KEYS`. Cloud SQL already passed the migration.
  - **Expect:** exit 0 and `failed=0`. A second run reports `encrypted=0 failed=0`.
- [ ] **Transfer, while `chmarine-product-service` is still running.** Set CH Marine's
  `transfer_to_team` tool to **Static** with the current `TRANSFER_DESTINATION` (e.g.
  `PJSIP/200@voiptel`). Place a test call and ask for a person.
  - **Expect:** the destination rings, and there is no "Allocation failed" in the api log.
  - **Then:** stop the product service. Repeat the transfer test call.
  - **Expect:** it still rings.
- [ ] **Voiptel.** Book, cancel and run an order lookup through fallcha-tools.
  - **Expect:** the event title starts with `Voiptel call`.
- [ ] **CH Marine.** Run a product search and a product detail through fallcha-tools.
  - **Expect:** answers match the old service's style.

## Sign-off

| Area | Result | Notes |
|---|---|---|
| Env and bootstrap | | |
| Calendar SA / OAuth | | |
| Sheets reuse | | |
| Website catalogue | | |
| Calls: book / cancel / restore | | |
| Refresh / revoke / reconnect | | |
| Credential encryption | | |
| Skills | | |
| nginx | | |
| GCP cutover | | |
