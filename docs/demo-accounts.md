# Demo accounts

Four invented Irish businesses, each with a month of calls and a real,
working agent, for showing LightMove.ai to prospects. Everything in them is
made up: the businesses, their people, their callers and every phone number
(all in the 555 range; none is ever dialled).

A fifth, CH Marine, is built on a real company's published facts for a
partner presentation: see `docs/demo-chmarine.md` (`--only chmarine`).

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
  demo number `+353 1 555 0100` (see "Transfers" below).
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
- **Email reports**: daily (at 6 pm, covering the 24 hours since the last
  one) and weekly (Mondays at 8 am), to the owner's address (confirmed).
  Locally, Mailpit (http://localhost:8025) catches them. A daily sent before
  the refresh has run says "no calls": refresh before 6 pm on the demo day.

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

- **Phone numbers.** The seed links none. Locally, Linen Quay answers the
  Asterisk extension `7000` and CH Marine `7002` (linked by hand for the
  phone tests), so their Home says "Answering calls · 7000". The other three
  have no number, and their Home says so in a red banner.
- **Bookings** reads live from a connected calendar, so it only lists real
  bookings. The seed connects none: it says "Connect your calendar". The
  seeded history still has calls where a booking was made, so Home counts
  "bookings taken" and Calls shows them. Locally, Linen Quay and CH Marine
  are connected to the test Calendly (lightmove.ai@gmail.com), so a test
  call can book for real: it appears on Bookings (List or Week), with the
  phone number and party size the caller gave, and Calendly emails the
  address the caller spelled out. Its slot length is the Calendly event
  type's (30 minutes on the test account).
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
   no call review (reviews are written for phone calls only). Home looks
   for new calls by itself (every 30 seconds, and a few seconds after the
   test panel closes); **Refresh** next to the date range looks now.

The restaurant agent opens with "How can I help you today?", asks how many
people before looking for times, spells a corrected email back before
booking, and before saying goodbye asks whether there's anything else or
whether the caller wants to speak to someone on the team.

In a demo workspace it also lands on **Home** and **Follow-ups** like a
phone call (anywhere else, browser tests stay off those pages), so a
prospect sees their own call arrive.

The refresh keeps test calls. Anything you say on one stays on Home and
Follow-ups until it is marked done or deleted, so give a made-up name and a
555 number, never your own. Only the owner (or an admin) can start one:
staff don't see Try your agent.

### Transfers

"Pass calls to your team" is on for every demo agent, set to the demo
number `+353 1 555 0100` (stored as `+35315550100`) through the wizard's
own "Number to put callers through to a person" answer. It looks like a
Dublin landline so it passes the number check, but it could belong to a
real person, so the transfer code never dials it: the list of reserved
demo numbers is `DEMO_TRANSFER_NUMBERS` in `api/utils/transfer_number.py`
(it also holds the old placeholder `+3530000000`). The agent's "What your
agent knows" page marks it "Demo number – change it before a live
transfer". To change it: open the agent, go to **What your agent knows** ›
**Pass calls to your team**, type the number and save. The next call uses
it.

Agents seeded with the old placeholder `+3530000000` get the new number
the next time the seed runs (only against a local database).

For a real phone test, put your own mobile in, and put the demo number back
afterwards: the seed copies the agent's settings into every seeded call, so
a real number left there ends up in the demo data.

In a browser test call, asking for a person makes the agent try the
transfer; the engine refuses it ("call transfers are not available for web
calls"), the agent says so and offers to take a message. On a phone call
(once a number is linked), the transfer to the demo number is not dialled:
it is stored as a transfer nobody answered (reason `demo_number`), which
Home counts and Follow-ups lists, and the agent takes a message.
