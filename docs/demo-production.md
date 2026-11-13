# The live demo workspace: what to do

For: whoever runs production (Alok). Time: about 20 minutes the first time,
then one button press before each demo.

## What you get

One workspace on app.lightmove.ai called **LightMove Demo**, with:

- five agents, one per made-up business: Linen Quay Kitchen (restaurant),
  Halyard Telecom (phone provider support), Larchfield Dental (clinic),
  Tidewell Plumbing & Heating (trades) and CH Marine (marine shop);
- two logins: `lightmove-demo.owner@demo.lightmove.ai` (admin) and
  `lightmove-demo.staff@demo.lightmove.ai` (staff), sharing one password kept
  in Secret Manager;
- a month of made-up calls ending today (about 460), with recordings for the
  newest 20 of each business, follow-ups, bookings and reports.

It is the same data as the local demo, built by the same script
(`api/scripts/seed_demo_accounts.py`). Every business, person and phone
number is invented (all numbers in the 555 range, never dialled), except
CH Marine, which uses CH Marine's own published product and price details.

**Email.** The demo addresses have no mailbox, so the daily and weekly email
reports stay **off**. On Reports, **Email me** lets the presenter type any
address (a prospect's, their own) and sends that report once, in the
LightMove email design. Nobody is added to a mailing list. Only owners and
admins can type an address; staff can only send to themselves.

**Phone calls.** No phone number is linked. Prospects try the agents with
**Try an agent** in the browser. The report email and Home say "No phone
number is linked to your agent yet": that's true, and it stays until a
number is linked. **To decide (Alok):** link a real number to one demo
agent, or keep the demo browser-only.

## One-time setup

1. **Ship the code.** Merge the PR, run **Release**, then **Deploy** as
   usual. The seed and the server script ship inside the release; the
   **Seed demo** workflow appears in Actions once the PR is on main.

2. **Set the demo password** in Secret Manager. Pick a new one (12+
   characters, not the local `LightMoveDemo2026!`), then:

   ```bash
   printf '%s' 'THE-NEW-PASSWORD' | gcloud secrets create lightmove-demo-password \
     --project dograh-eu --replication-policy automatic --data-file=-
   gcloud secrets add-iam-policy-binding lightmove-demo-password --project dograh-eu \
     --member serviceAccount:dograh-app-sa@dograh-eu.iam.gserviceaccount.com \
     --role roles/secretmanager.secretAccessor
   ```

   Share the password with presenters the way you share other team
   passwords. It never appears in logs or on a command line.

3. **Text-to-Speech is on** (it already is if voice previews play on the
   live site): `gcloud services list --enabled --project dograh-eu | grep texttospeech`.
   The first run synthesises the recordings, about 52,000 characters, roughly
   €1.50. Later runs reuse what they made only while the api container lives,
   so a run after a deploy synthesises again.

4. **Run it.** GitHub → Actions → **Seed demo** → Run workflow:
   - action: `refresh`
   - workspace: `LightMove Demo`
   - confirm: `seed production`

   It checks the VM is up, takes a Cloud SQL backup (`demo-seed …`, pruned
   after 30 days), then runs the seed inside the live api container. The job
   summary lists the workspace, the two logins and each business's counts.

5. **Check it.** Sign in at https://app.lightmove.ai/auth/login as the owner.
   Home shows today's calls for all five businesses; **Try an agent** lists
   the five agents. On Reports, use **Email me** with your own address and
   check the email arrives.

6. **Give it credit** so test calls work: Super admin → Organizations →
   LightMove Demo → **Add credit**, type Adjustment (e.g. €20, reason "demo
   workspace"). Test calls use real model time.

7. **Bookings (optional).** Signed in as the demo owner: Integrations →
   Calendly → connect lightmove.ai@gmail.com, then on Linen Quay's and
   Larchfield's "What your agent knows", turn on **Take bookings**. The
   local Calendly connections can't be copied: the access was granted to
   the local app only.

## Before each demo

Run **Seed demo** with `refresh`. The made-up month moves to end today, so
Home shows "today" calls. Logins, agents, credit and Calendly are kept, and
so are calls made on the day (test calls). The seed does put back each
agent's opening hours, its safety rules and CH Marine's price list, orders
and order-lookup tool, so change those in the seed, not on the live agent.

## Other actions

| Action | What it does |
|---|---|
| `refresh` | Builds the workspace if it isn't there, otherwise replaces the made-up calls with a fresh month. |
| `reset` | Deletes the workspace (agents, calls, recordings, files, tools, credit, logins), then builds it again. Reconnect Calendly and add credit afterwards. |
| `delete` | Deletes the workspace, its two logins and every recording of its calls. |

## Without GitHub Actions

From a machine with IAP access:

```bash
gcloud compute ssh dograh-app --zone europe-west1-b --project dograh-eu --tunnel-through-iap \
  --command "bash -s -- refresh 'LightMove Demo' /opt/lightmove/dograh" < deploy/gcp/seed-demo.sh
```

Take a Cloud SQL backup first if you go this way.

## What it can and can't touch

- It only changes a workspace marked as a demo one: provider id
  `demo_lightmove_lightmove-demo`, a `DEMO_ACCOUNT` setting, and every member
  at `@demo.lightmove.ai`. It refuses any other workspace, including if a real
  person is added as a member.
- On production it refuses to run unless all of these hold:
  `ENVIRONMENT=production`, `--production`, `DEMO_ALLOW_PRODUCTION=yes`,
  `--workspace "<name>"`, and a `DEMO_PASSWORD` of 12+ characters that isn't
  the local default. The server script sets them; nothing else does.
- No call is placed, nothing is billed, no model reviews the made-up calls,
  and no email is sent by the seed.
- Each call's public listen link gets a random token.

## If something goes wrong

| What you see | What to do |
|---|---|
| `Cannot read secret 'lightmove-demo-password'` | Step 2: create the secret and grant `dograh-app-sa` access. |
| `The api service isn't running` | Deploy first, or start the stack. |
| `starter template … is missing` | The api syncs templates on start; restart the api container. |
| `TTS 403` | Enable Text-to-Speech for dograh-eu, or check the VM service account's access. |
| `Refusing to seed the live site: …` | The message names the missing opt-in. |
| Wrong data, or you want it gone | Run `delete`; the backup from the run is in Cloud SQL backups. |
