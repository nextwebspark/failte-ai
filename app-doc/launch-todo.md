# Launch to-do list

Everything still open before launch, including placeholders. Mirrors the
To-do list on the "LightMove Launch Readiness" page; last updated 10 Nov 2026.
Tick items here (`[x]`) as they're done.

Related: `app-doc/call-setup.md` (calls, transfers, providers, real phone test plan).

## Placeholders to fill: website legal pages and docs (lightmove-website)

- [ ] **Privacy policy: retention periods**: `[ENQUIRY RETENTION PERIOD]` and `[LOG RETENTION PERIOD]` in `src/content/legal/privacy.md`. The enquiry period also shows under the contact form.
- [ ] **Terms of service**: `[CONFIRM BILLING CYCLE, CREDITS AND REFUND POLICY]` and `[LEGAL REVIEW REQUIRED]` in `terms.md`; `[CONFIRM REFUND POLICY]` in `docs/account/billing.md`.
- [ ] **Data Processing Agreement**: `[CONFIRM POSITION ON SPECIAL CATEGORY DATA]`, `[CONFIRM AUDIT NOTICE PERIOD AND FREQUENCY]`, `[CONFIRM HOW DATA IS RETURNED OR EXPORTED]` and two `[CONFIRM]` in `dpa.md`.
- [ ] **Sub-processors**: Location and safeguard per carrier, any other carriers on the account, and the transfer safeguard for Firebase Hosting, in `subprocessors.md`.
- [ ] **Cookie policy**: `[CONFIRM WHICH SIGN-IN METHOD PRODUCTION USES]` in `cookies.md`.
- [ ] **Solicitor review**: Recording notice and lawful basis, health data on GP/dental calls, and the legal pages above, before they're published.

## Keys, accounts and addresses you need to provide

- [ ] **Resend key for the website contact form**: Set the contact function's `RESEND_API_KEY` secret. Until then the form says "Your message wasn't sent".
- [ ] **Google Calendar service account**: Needed for the Bookings page and for demo accounts to book tables and appointments.
- [ ] **LightMove's own Twilio account**: `PLATFORM_TWILIO_ACCOUNT_SID`, `PLATFORM_TWILIO_AUTH_TOKEN`, plus an approved Irish compliance bundle and address (`PLATFORM_TWILIO_BUNDLE_SID`, `PLATFORM_TWILIO_ADDRESS_SID`). Switches on "LightMove provides the number".
- [ ] **Create the lightmove.ai mailboxes**: `support@lightmove.ai` (Help tickets and the app's support links now go here) and `privacy@lightmove.ai` (13 places on the website). Also used: `hello@lightmove.ai` (website contact), `legal@lightmove.ai` (legal pages) and `sales@lightmove.ai` (app). Check that each receives mail before launch.
- [ ] **Where internal emails go**: Help tickets default to `support@lightmove.ai` (override with `SUPPORT_EMAILS`). Still to set: `VOICE_REQUEST_EMAILS` (custom voices) and `OPERATOR_ALERT_EMAILS` (platform alerts).
- [ ] **Set up docs.lightmove.ai**: Create the second Firebase Hosting site for the docs, connect the custom domain `docs.lightmove.ai` and add the DNS records Firebase asks for. Old `lightmove.ai/docs/…` links redirect there.
- [ ] **Demo password for shared servers**: Set `DEMO_PASSWORD`; the local default must not be used outside this computer.
- [ ] **Website "Talk to Aoife" demo token**: `PUBLIC_DEMO_AGENT_TOKEN` for the homepage demo agent.
- [ ] **Optional: Calendly OAuth app**: Client id and secret, if owners should sign in to Calendly instead of pasting a token.
- [ ] **Telnyx test account and an Irish number**: For the first real phone test (see the "LightMove Call Setup" page). $10 top-up; Telnyx needs ID and a proof of address in the number's area before it sells an Irish local number. Paste the API key and webhook public key into LightMove yourself.
- [ ] **Calendly time zone**: Set your Calendly availability schedule and profile time zone to Dublin (the agent offered 4 am because Calendly's 9–6 is in another zone), or set Time zone to `Europe/Dublin` on the LightMove Calendly connection. Then book one real test slot and cancel it.

## Decisions waiting on you

- [ ] **Price for LightMove-provided numbers**: Billing for them is switched off; the hook is marked `TODO(billing)` in `platform_numbers/service.py`.
- [ ] **Monthly cap and bundles**: Whether to add "never spend more than €X" and bundles next to €0.12/min, given IONOS and Fasthosts pricing.
- [ ] **Faster replies**: Shorten the "caller has finished speaking" pause. Faster answers, small risk of interrupting. Needs a test call with you.
- [ ] **Calls page Outcome filter**: It now sits under More filters. Bring it back to the main bar, rebuilt on the new outcome wording?
- [ ] **"Covers" wording**: Keep "Covers booked" or say "Guests booked".
- [ ] **Reports reset**: Should "Reset to the pack" also clear the owner's average spend?
- [ ] **What the "Owner" role may do**: Owner (the business owner on an account someone else manages) can keep facts and answers up to date, run bookings and reports. It can't start a test call, change the voice, request a custom voice, set up a phone number or open Integrations. At least the test call looks wrong.
- [ ] **Support ticket inbox**: Tickets (LM-1234) are emailed to `SUPPORT_EMAILS` and stored, but status can only be changed in the database. Decide whether we need an admin screen or a helpdesk tool.
- [ ] **CH Marine line 7002 (with Alok)**: Keep the separate local extension 7002, point 7000 at CH Marine while testing, or remove 7002 until a real number exists.
- [ ] **Which provider for real numbers**: Telnyx for the test (cheapest full-featured); Twilio for LightMove-provided numbers as planned, or move those to Telnyx too.

## Calls at the same time

- [x] **Done: don't hang up on callers when lines are full**: Built (PR #156): forward to the team or take a voicemail on Twilio and Telnyx, busy message elsewhere, "Lines were busy" follow-ups, a "Calls at once" card in Settings and a Reports card.
- [ ] **Test busy lines on a real number**: Only tested with simulated calls. On the Telnyx test number, set the limit to 1 (platform admin), ring twice at once, and check the forward and the voicemail.
- [ ] **Load test before launch**: The planned app server has 2 cores. Measure how many simultaneous calls it handles with good reply times, then size servers and per-business limits from that.

## Testing only you can do

- [ ] **Listen to the Irish name samples**: Before/after clips in the session scratchpad `ttsprobe` folder, and the Aoife Connolly demo call.
- [ ] **Cancel the 7000 forwarding on your mobile**: Dial `##61#` (or `##002#`) if not done already.
- [ ] **Fix the local Asterisk endpoint**: Telephony → Edit credentials → ARI Endpoint `http://host.docker.internal:8088`.
- [ ] **First real phone test**: Follow the step-by-step plan on the "LightMove Call Setup" page: Linen Quay agent on a Telnyx number, a second phone as the caller, your mobile as the staff phone. Check the transfer, the caller's number on your phone, an unanswered transfer and Follow-ups.
- [ ] **Try the CH Marine demo end to end**: Order lookup with the sample orders, the closing offer to connect with staff, and Calendly booking once the time zone is fixed.

## Merges and releases awaiting your go-ahead

- [ ] **App: review and merge PRs #154 → #155 → #156, in that order**: The whole of `claude/ux-pass-2`, split in three stacked PRs; review requested from nextwebspark. #154 already contains the open PRs #140, #141, #143, #146–#152, which can be closed once it merges.
- [ ] **Website: three branches**: `claude/website-pricing` (real prices, highlighted middle plan), `claude/contact-email-fallback` (topic chips open the form), `claude/phase0-mobile-header`.
- [ ] **Production demo accounts**: Run the demo seed on a shared server only with your approval and a real `DEMO_PASSWORD`.

## Housekeeping

- [ ] **Remove local test data when testing ends**: Seeded runs in the first test workspace (org 4), the sample sign-up accounts, and the copied recordings in local storage.
- [ ] **Flaky test on main**: `test_answer_supervisor_late_speech` fails on main in about 3 of 5 runs (a timing race), so CI can go red at random. Worth a small fix PR.
- [ ] **Earlier open items**: Testing-lab failures (gas number, transfer with no number, Eircode, feedback score, Polish caller) and the guardrails P1 list.
