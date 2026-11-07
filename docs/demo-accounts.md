# Demo accounts

Four invented Irish businesses, each with a month of calls and a real,
working agent, for showing LightMove.ai to prospects. Everything in them is
made up: the businesses, their people, their callers and every phone number
(all in the 555 range; none is ever dialled).

They are built by `api/scripts/seed_demo_accounts.py` (the business and call
scripts are in `api/scripts/demo_businesses.py`). Local and development
databases only: the script refuses to run with any other `ENVIRONMENT`.

## The logins

All eight share one password: the `DEMO_PASSWORD` environment variable when
the seed ran. When it is not set, the seed uses a local default and prints it.

| Business | Owner (admin) | Staff |
| --- | --- | --- |
| Linen Quay Kitchen, a restaurant in Galway | `linen-quay.owner@demo.lightmove.ai` | `linen-quay.staff@demo.lightmove.ai` |
| Halyard Telecom, a VoIP provider's support line, Dublin | `halyard-telecom.owner@demo.lightmove.ai` | `halyard-telecom.staff@demo.lightmove.ai` |
| Larchfield Dental, a family practice in Kilkenny | `larchfield-dental.owner@demo.lightmove.ai` | `larchfield-dental.staff@demo.lightmove.ai` |
| Tidewell Plumbing & Heating, Cork | `tidewell-plumbing.owner@demo.lightmove.ai` | `tidewell-plumbing.staff@demo.lightmove.ai` |

The owner has the role a self-signed-up owner gets (admin): they can edit
the agent, its facts and the email reports, and test it. The staff member
has the staff role: they see Home, Calls, Follow-ups and Reports, and can
mark follow-ups done, but cannot change the agent.

## What each business shows

Every business has:

- **An agent** made from its starter template by the same endpoint the
  Create agent wizard uses, with the business's facts filled in (name,
  description, hours, address, website, common questions) and
  `template_category` set. "Pass calls to your team" is on, with the
  placeholder number `+3530000000` (see "Transfers" below).
- **60–120 inbound calls over the last 30 days**, at the business's busy
  hours and days. Each call is stored the way a real phone call is: the
  call log (`logs.realtime_feedback_events`), what the agent wrote down
  (`gathered_context`), the call status, a transcript file, and a call
  review (`annotations.call_review`, written by the seed with model
  `demo-seed`, matching the transcript; no model is called).
- **Recordings** for the 20 newest calls: each transcript read by two
  Google TTS voices (the agent's default voice and a British English
  caller voice), stored in MinIO exactly where real recordings go
  (`recordings/<id>.wav` plus the caller and agent tracks). Listen, Share
  recording and Download work on these. Older calls have the transcript
  only.
- **Follow-ups**: callbacks, transfers nobody answered, questions the
  agent couldn't answer and times that were full. Those older than three
  days are marked done (mostly by the staff member), about half of the
  last three days are done, and the last few hours are open.
- **Email reports**: daily and weekly, to the owner's address (confirmed).
  Locally, Mailpit (http://localhost:8025) catches them.

| Business | Template | What callers ring about |
| --- | --- | --- |
| Linen Quay Kitchen | Restaurant bookings | Table bookings (made, full, big groups), takeaway orders, hours, allergies, parking, the manager |
| Halyard Telecom | VoIP phone receptionist (category "telephony") | Outages put through to a technician, billing, number porting, sales quotes |
| Larchfield Dental | Clinic receptionist | Appointments, emergencies (toothache, broken tooth), new patients, prices, cancellations |
| Tidewell Plumbing & Heating | Trades after-hours | Burst pipes put through to the engineer on call, no heat, boiler services, quotes, existing jobs |

The telecoms line uses the general "What callers wanted" categories
(Questions, Speak to someone, ...): the telephony starter has no set of its
own.

### What these screens can't show

- **No phone number is linked.** Home says "Your agent isn't answering: no
  phone number is linked" in a red banner. That is true: the demo
  workspaces have no phone line, and the seed does not invent one.
- **Bookings is empty** ("Connect your calendar to take bookings"). The
  Bookings page reads live from a connected Google Calendar and no calendar
  is connected. The seeded history still has calls where a booking was
  made (as if a calendar had been connected then), so Home counts
  "bookings taken" and Calls shows them; the live agent, with no calendar,
  takes a message for a booking instead.
- **Today** is only as busy as the time of day allows: run the refresh on
  the morning of the demo (after 10am a handful of calls today is
  guaranteed). Just after midnight Today is empty and honestly so.

## Before a demo: refresh

    python -m api.scripts.seed_demo_accounts

Locally, run it in a one-off container from the API image, with the
repository mounted, for example:

    docker run --rm --env-file <api env file> \
      -e DEMO_PASSWORD=... -e DEMO_TTS_CACHE=/cache -v <cache dir>:/cache \
      -v <service account json>:/secrets/gcp.json:ro \
      -v <repo>:/repo -w /repo lightmove-api:local \
      python -m api.scripts.seed_demo_accounts

This keeps the workspaces, logins and agents (and any change made to the
agent, such as a transfer number) and replaces the seeded calls with a
fresh month ending now. Test calls made during a demo are kept. Synthesised
speech is cached in `DEMO_TTS_CACHE`, so a refresh only pays for speech it
hasn't made before (a first run synthesises about 19,000 characters).

Options:

- `--reset` deletes the four demo workspaces, their users, calls, test
  calls and stored files, then builds them again.
- `--delete` only deletes them.
- `--only <slug>` works on one business (repeatable).
- `--recordings N` records the newest N calls per business (default 20).
- `--no-audio` makes no recordings and no TTS calls.

Only workspaces carrying every demo marker are touched: the provider id
`demo_lightmove_<slug>`, a `DEMO_ACCOUNT` configuration row, and every
member's address at `@demo.lightmove.ai`. Anything else makes the script
stop.

The seeded calls are never billed: no completion job runs for them and they
carry no cost.

## A live test call in the demo

1. Log in as the owner.
2. On Home, press **Try your agent** (or open the agent and press **Test
   agent**). Allow the microphone and talk to it like a caller: book a
   table, ask about parking, report an outage.
3. The call appears on **Calls** as soon as it ends, as a "Test call",
   with its recording, transcript and what the agent wrote down. It gets
   no call review (reviews are written for phone calls only).

It does not appear on **Home** or **Follow-ups**: those count inbound
phone calls only, and a browser test call is not one. To show a call
landing on Home and Follow-ups, the workspace needs a linked phone number
and a real call to it.

### Transfers

"Pass calls to your team" is on for every demo agent, set to the
placeholder `+3530000000` through the wizard's own "Number to put callers
through to a person" answer. To change it: open the agent, go to **What
your agent knows** › **Pass calls to your team**, type the number and save.
The next call uses it.

In a browser test call, asking for a person makes the agent try the
transfer; the engine refuses it ("call transfers are not available for web
calls"), the agent says so and offers to take a message. On a phone call
(once a number is linked), a transfer to the placeholder fails and is
stored as a transfer nobody answered, which Home counts and Follow-ups
lists.
