# Call setup: how a call reaches the agent, and how it gets to a person

Last checked against the code: 10 Nov 2026 (branch `claude/ux-pass-2`, PRs #154–#156).

How calls reach a LightMove agent, how the agent puts a caller through to a
person, what happens when every line is busy, what each phone provider
supports, and a step-by-step plan for the first test with a real Irish number.

Related:
- Customer-facing version, in plain words for owners: `docs/customer-guides/phone-and-transfer-setup.md`.
- Provider internals: `app-doc/telephony-architecture.md`.
- The ARI transfer path on the live CH Marine Asterisk: `app-doc/call-transfer-to-human.md`.

## The whole call

```
Caller ──▶ Business number ──(forward, optional)──▶ Agent's own number ──stream──▶ LightMove ──▶ AI agent
           (eir, Vodafone,                          at a phone provider          picks the agent
            a mobile…)                              (Telnyx, Twilio, Asterisk)    for that number
                                                                                     │
                                                         caller asks for a person    ▼
                                                                               Staff phone
                                                                     (no answer ▶ Follow-ups)
```

Every agent needs a number at a phone provider. Forwarding from the business
number is optional: it is how a business keeps the number customers know.

## How callers reach the agent

The owner answers "How should callers reach your agent?" on the agent's
**Phone number** screen.

| Choice | Who it's for | How |
|---|---|---|
| Keep my existing number | Most businesses | The business number forwards to the agent's number |
| Get a new number | A number just for the agent | Printed on the website and Google profile; no forwarding |
| My mobile is my business number | Sole traders | The mobile forwards to the agent, usually when not answered |

Forwarding codes (most mobiles; landlines are set by the phone company):

| Forward when | Caller experience | Code |
|---|---|---|
| Not answered (recommended) | Owner's phone rings first, agent picks up after ~20 s | `**61*<agent number>**20#` |
| Busy | Only when the line is engaged | `**67*<agent number>#` |
| All calls | Agent answers everything | `**21*<agent number>#` |
| Undo | Cancels every forward | `##002#` |

The screen fills the codes in with the agent's number, and "I've set it up,
check now" waits for a real call (LightMove never places a test call).
Extensions such as the local `7000` can't be forwarded to, so the screen says
so instead of showing a code (`phoneForwarding.ts`, `isPublicNumber`).

## Passing a caller to a person

Set in **What your agent knows › What your agent can do › Pass calls to your team**.

1. The caller asks for a person. The agent says "One moment, I'm putting you through".
2. The caller hears hold music while the staff phone rings. On Twilio and
   Telnyx this is a small conference (`TelnyxConferenceStrategy` and the
   Twilio equivalent): the caller is parked in it, LightMove rings the staff
   number and joins them when it is answered.
3. Answered: staff and caller talk and the agent drops off. Twilio can first
   play a short "you have answered a transfer call" announcement
   (`supports_transfer_introduction`).
4. Not answered in about 30 seconds: the agent comes back, apologises and
   takes name, number and reason. The call shows in Follow-ups as
   "Transfer not answered".

Rules around it:
- **Only during opening hours**: on by default once opening hours are set as
  times. Outside them the agent rings nobody and takes a message (a
  Follow-up). Turn it off for emergency call-outs.
- **What the staff phone shows**: on Twilio and Telnyx numbers, the caller's
  number (`CALLER_NUMBER_PROVIDERS`); the agent's number if the caller
  withheld theirs or the provider refuses. Other providers show the agent's
  number. Owners can switch it off.
- **No number set**: the agent never transfers; it takes a message.
  Browser tests ("Try your agent") never transfer.
- **Forwarding loop**: if the staff number forwards to the agent, the call
  goes round in circles. LightMove refuses the agent's own numbers but can't
  see a forward set on the phone network. Use a phone that isn't forwarded.
- **Voicemail**: if the staff phone's voicemail answers within 30 s, the
  caller lands there instead of leaving a message with the agent.

## When every line is busy

Each business takes a set number of calls at once (10 by default; a platform
admin can change it per business). The next caller is turned away, and hears
what the owner chose under **When all lines are busy**:

| Option | What happens | Providers |
|---|---|---|
| Put them through to your team | Rings the transfer number; voicemail if nobody answers | Twilio, Telnyx |
| Take a voicemail | "Lines are busy", then they leave name and number | Twilio, Telnyx |
| Just say we're busy | A short message, then the call ends | All (the only option elsewhere; Asterisk hangs up the channel) |

Turned-away calls are saved as `LINES_BUSY`, aren't billed, appear in
Follow-ups ("Lines were busy") and are counted on Home and in the Reports card
"Callers who couldn't get through". `LINES_BUSY_PROVIDERS` in
`api/services/calls/lines_busy.py`.

## What each provider supports

| Provider | Put callers through | Caller's number on staff phone | Busy lines: forward / voicemail |
|---|---|---|---|
| Telnyx | Yes | Yes | Yes |
| Twilio | Yes (with announcement) | Yes | Yes |
| Asterisk (ARI), e.g. with Voiptel | Yes | Agent's number | Busy message only |
| Plivo, Cloudonix | Yes | Agent's number | Busy message only |
| Vonage, Vobiz, Exotel | No | n/a | Busy message only |

From `supports_transfers()` in each `api/services/telephony/providers/*/provider.py`.

## First real phone test (Telnyx)

Goal: ring a real Irish number, talk to the Linen Quay restaurant agent, ask
for a person, and have Naveen's mobile ring as the staff phone.

Why Telnyx: pay as you go with a $10 minimum top-up and no monthly minimum,
Irish local numbers from about $0.50–1 a month, and every feature above.

**Two phones are needed.** The mobile that rings as "staff" can't also be the
caller: it's busy on the call, so the transfer would fail or hit voicemail.

1. **Open a Telnyx account and add $10.** New accounts are verified before
   international numbers can be bought; allow a day.
2. **Buy an Irish local number** (e.g. Dublin, 01). Search Ireland → Local,
   not Mobile: Telnyx has no Irish mobile numbers, and the agent doesn't need
   one. If no local numbers show either, use Twilio ($1.80 a month) or Plivo
   ($0.85 a month, fewer features). Telnyx asks for a name,
   contact details, ID (personal) or company registration (business), and an
   address in the number's area with proof of address from the last 3 months.
   Approval can take a few days.
3. **Make the local API reachable.** Telnyx posts call events and streams audio
   to the API; `localhost` isn't reachable from the internet. A free Cloudflare
   quick tunnel works: `cloudflared tunnel --url http://localhost:8000`. Set
   `BACKEND_API_ENDPOINT` to the https address it prints and restart the API.
4. **Connect Telnyx in LightMove.** Log in as the Linen Quay owner → agent →
   Phone number → "Advanced: use my own phone provider account" → Telnyx.
   Paste the API key and the webhook public key (Telnyx portal → Keys &
   Credentials) yourself; leave "Call Control App ID" blank (LightMove creates
   one). Pick the new number for the agent.
5. **Set the staff phone.** What your agent knows → Pass calls to your team →
   the mobile. It replaces the safe demo number. Turn "Only during opening
   hours" off while testing, or test inside the restaurant's hours.
6. **Run the calls** from the second phone:
   - book a table for Friday, then ask about allergens;
   - ask for the manager: the mobile should ring showing the caller's number; answer it;
   - ask again and let the mobile ring out: after ~30 s the agent takes a message; check Follow-ups;
   - optional: forward the second phone to the agent (`**61*…**20#`), let it
     ring out, check "Forwarded from your number", then cancel with `##002#`.
7. **Check in LightMove**: Home tiles, recordings and transcripts, the
   transfer outcome, Follow-ups.
8. **Afterwards**: put the demo transfer number back, stop the tunnel, set
   `BACKEND_API_ENDPOINT` back to localhost. Keep the number for demos if
   useful.

Busy lines can be tested on the same number: set the business's limit to 1
(platform admin), ring from two phones at once, check the forward and the
voicemail.

Alternatives:
- **Twilio free trial**: free credit, but calls only to and from verified
  numbers, a "trial account" message on calls, and Irish numbers need a
  regulatory bundle a trial may not get. Fine for a quick check, not demos.
- **Voiptel** (Irish SIP carrier, through Asterisk): possibly cheapest if a
  spare number exists on the current account, but no caller's number on the
  staff phone and no busy-line forwarding. The live `asterisk-voiptel` deploy
  belongs to the production setup; don't change it for tests.

## Costs (check live rates before relying on them)

| Item | Telnyx | Twilio |
|---|---|---|
| Start | $10 minimum top-up, no monthly minimum | Free trial credit; paid use needs an upgrade |
| Irish local number | from $0.50–1 a month | $1.80 a month |
| Calls coming in | see the Telnyx rate card | $0.01 a minute |
| Putting a call through to an Irish mobile | see the Telnyx rate card | $0.0945 a minute while the staff leg is up |

LightMove's own cost (speech, model, voice) is per minute the agent is on the
call, the same as today; it doesn't count the conversation after staff answer.

Sources: Telnyx [Ireland numbers](https://telnyx.com/phone-numbers/ireland),
[numbers pricing](https://telnyx.com/pricing/numbers),
[billing setup ($10 minimum)](https://support.telnyx.com/en/articles/4280500-billing-setup-billing-groups),
[Ireland number requirements](https://support.telnyx.com/en/articles/1311458-ireland-did-requirements);
Twilio [voice pricing in Ireland](https://www.twilio.com/en-us/voice/pricing/ie),
[trial restrictions](https://help.twilio.com/articles/360036052753),
[Ireland regulatory guidelines](https://www.twilio.com/en-us/guidelines/ie/regulatory).
