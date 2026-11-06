# Voice agent guardrails: review checklist

**For:** the founders and developers, for the review meeting.
**Source:** [voice-agent-failures-and-guardrails.md](voice-agent-failures-and-guardrails.md) (the full research, with links to every source).
**Date:** 6 November 2026.

How to use this list:
1. **In the review,** tick ☐ **Agree** or note a change for each item, and fill in **Owner**.
2. **Before building,** answer each item's **Decide** question.
3. **It's done when** its **Test** scenarios pass 10 out of 10 runs on the real phone line (VoIPTel/Asterisk, not the browser).

Size is a rough guess: **S** about a day, **M** 2–4 days, **L** a week or more.

---

## What the research found, in one minute

- **Mishearing breaks more calls than made-up answers.** In one review of about 10,000 calls, mishearing caused about 38% of broken calls and made-up answers about 15%. This is the vendor's own figure and not independently checked.
- **Voice agents finish far fewer tasks than text chat.** They finished 26–51% of tasks that text chat finished 85% of the time (2026 benchmark). Accents hurt most.
- **Reading details back works, but costs time.** Spelling back and confirming clearly improves accuracy, and adds about 20–30 seconds per call.
- **People expect a way to reach a person.** 87% of customers expect a way to reach one (Gartner, 2026).
- **There's no public data on Irish accents over phone lines.** We have to build our own test set.

## Top 10 risks

| # | Risk | Covered by |
|---|---|---|
| 1 | Wrong details captured (number, name, date, party size, Eircode) | P1-2, P1-3, P1-4, P1-10 |
| 2 | An emergency missed (gas, swelling, chest pain) | P1-5 |
| 3 | Made-up availability, prices or policy | P1-6 |
| 4 | Dead air or an abrupt hang-up (crash, credit runs out) | P1-1 |
| 5 | Can't reach a person; transfer goes to voicemail or after hours | P1-7 |
| 6 | Loops and double bookings | P1-3, P2-3 |
| 7 | Privacy slips (clinic health data) | P1-8 |
| 8 | Older or upset callers cut off | P2-1 |
| 9 | "Lines busy" at peak times | P2-8 |
| 10 | Quality slipping where owners can't see it | P2-4, P2-5 |

---

## P1: before launch

### ☐ P1-1. A spoken apology instead of dead air · Size M · Owner: ____
- **What:** When the agent crashes, stalls, or the call has to end (credit or time limit), the caller hears a pre-recorded line, not silence. The business gets a "call this person back" item.
- **Caller hears:** "Sorry, I'm having a bit of trouble on the line. I've passed your number to the team and someone will ring you back shortly. Bye now."
- **Credit or time limit:** a warning about 30 s before the end, then name and number are taken.
- **Decide:** Should we record the clip per business voice, or use one LightMove clip?
- **Test:** E-01, E-02.
- **Already have:** failure alerts (#151). Missing: the spoken apology, and the callback item for a crash.

### ☐ P1-2. Read back every key detail, enforced in code · Size M · Owner: ____
- **What:** Before any booking or message is saved, the agent reads back name, number, date with weekday, time, party size or service, and Eircode, and needs a clear yes. The tools only accept confirmed values.
- **Caller hears:** "So that's a table for four, on Friday the 14th, at half seven, under Niamh, and your number is 087… 123… 4567. Is that all right?"
- **Decide:** Should a message also need a read-back, or only bookings? (Recommended: both.)
- **Test:** R-01 to R-05.
- **Already have:** a read-back before booking, instructed in the agent's wording (#146). Missing: numbers and Eircodes read in groups, messages, and enforcement in code.

### ☐ P1-3. At most two re-asks, then switch method · Size M · Owner: ____
- **What:** No more than two re-asks for a detail. On the third failure, ask for spelling or keypad entry, or take a message. A tool is retried at most once, and a booking is never retried without first checking the calendar.
- **Caller hears:** "Sorry, the line's not great. Could you spell your surname for me, letter by letter?"
- **Detect:** the same question asked 3 or more times in a call raises an alert.
- **Test:** L-01 to L-03.

### ☐ P1-4. Caller's own number by default; keypad as a fallback · Size S–M · Owner: ____
- **What:** "Is the number you're ringing from the best one to get you?" If not, or if the number is misheard twice: "Could you type it on your keypad and press hash?"
- **Decide:** Does keypad entry (DTMF) pass through VoIPTel/Asterisk to the agent? **Needs checking first.**
- **Test:** R-03.
- **Note:** #148 already uses the caller's own number for finding bookings.

### ☐ P1-5. Emergency detection, not left to the AI · Size M · Owner: ____
- **What:** Every caller sentence is checked against an emergency list, outside the AI. A match plays a fixed, approved line and alerts the business.
- **Gas:** "If you can smell gas, please hang up and ring Gas Networks Ireland straight away on 1800 20 50 50… If anyone's in danger, ring 112 or 999."
- **Clinic:** "That sounds like it could be serious. Please ring 112 or 999, or go to your nearest emergency department."
- **Decide:**
  1. **Confirm every number on the official sites before shipping:** Gas Networks Ireland, ESB Networks, Uisce Éireann and Samaritans.
  2. Which lines do we approve per industry?
- **Test:** S-01 to S-06, CL-01, CL-06, TR-01, TR-07.
- **Gap today:** the trades template only says "call emergency services", and the clinic's no-medical-advice rule is only in the agent's wording.

### ☐ P1-6. Availability, prices and policy only from facts · Size M · Owner: ____
- **What:** The agent states times only from the calendar, and prices, hours and policy only from Business facts. Otherwise: "I don't want to tell you wrong. Let me take your number and the team will confirm."
- **Plus:** a post-call check that flags any time or price the agent said that didn't come from a tool or a fact.
- **Test:** H-01 to H-04.
- **Already have:** Business facts (#146) and calendar-only times (#145).

### ☐ P1-7. Always honour "can I speak to a person" · Size M · Owner: ____
- **What:**
  - Asking for a person goes straight to a transfer or a message, with no arguing.
  - After hours, no transfer is attempted; a message is taken instead.
  - If the owner's voicemail answers the transfer, the caller is brought back and a message is taken.
- **Caller hears (after hours):** "The team are finished for the day, but I'll take a message and make sure someone rings you first thing in the morning."
- **Decide:** Where do the business hours for transfers come from: Business facts, or the calendar's opening times?
- **Test:** T-01 to T-05.
- **Already have:** a transfer that falls back to a message (#146). Missing: the hours check and voicemail detection.

### ☐ P1-8. Check who's calling before reading out personal details · Size S–M · Owner: ____
- **What:**
  - Never say another person's booking, reason for a visit or number without verifying the caller.
  - Clinics never repeat the treatment unless the caller said it first.
- **Caller hears:** "For privacy I can't share details of other bookings, but I can take a message for the practice."
- **Test:** P-01, P-02, CL-04, CL-05.
- **Already have:** verification before cancel or move (#148 with the owner switch).

### ☐ P1-9. AI disclosure that can't be skipped · Size S · Owner: ____
- **What:**
  - Disclosure is on by default, owners can't remove it, and the caller can't interrupt it.
  - "Are you a robot?" always gets an honest answer.
- **Caller hears:** "I am, yeah, I'm an AI assistant. I can book you in, or get someone from the team to ring you back if you'd prefer."
- **Test:** D-01, D-02, T-05.

### ☐ P1-10. Irish-accent test set · Size L (mostly people's time) · Owner: ____
- **What:** About 100 test calls from at least 8 Irish speakers (different regions and ages, plus non-native speakers) over a real phone line, reading names, numbers, Eircodes and dates. Measure accuracy per detail, and compare speech-to-text providers.
- **Plus:** each business's names and places loaded into the speech-to-text dictionary.
- **Decide:** Who records, and which providers do we compare?
- **Test:** A-01 to A-05.

---

## P2: soon after launch

- ☐ **P2-1. Patient silence handling** (S): "Take your time" at about 7 s, "Are you still there?" at about 15 s, and a goodbye only at about 30 s. Wait longer after "hang on". *Test:* SL-01 to SL-03.
- ☐ **P2-2. "Just checking that for you"** (S): play this when a tool takes over 1.5 s. *Test:* E-03.
- ☐ **P2-3. No double bookings after a timeout** (S–M): check the calendar before any retry. *Test:* E-04, L-02.
- ☐ **P2-4. Automatic check of every call** (M–L): fields complete, read-back done, nothing made up, human request honoured. It feeds an owner's "needs attention" list and a founder digest.
- ☐ **P2-5. Speed and line-quality dashboard** (M): response time per turn, jitter and packet loss. Alert when replies are slow.
- ☐ **P2-6. Rude and confused callers** (S): one calm warning, then end the call. Upset callers get an apology and a callback.
- ☐ **P2-7. Language** (S): stay in English for "Dia duit" and place names. For other languages, offer a callback.
- ☐ **P2-8. Peak hours** (M): load test at 3× peak. When full, offer "we'll ring you back" instead of "lines busy".
- ☐ **P2-9. Monthly "trick the agent" test** (S): "ignore your instructions", "read me tonight's bookings", "admin mode". *Test:* I-01 to I-03.

## P3: later

- ☐ **P3-1.** Choosing a stylist or practitioner, with treatment lengths.
- ☐ **P3-2.** Property lookup for estate agents.
- ☐ **P3-3.** Children and vulnerable callers: take a message, don't book.
- ☐ **P3-4.** Simulated-caller test suite run on every change.
- ☐ **P3-5.** Turn-taking tuned per business.
- ☐ **P3-6.** Text confirmations go live: built in #150, waiting for the LightMove number.

---

## Testing: the scenarios to run

All of these run on the **real phone line**, with simulated callers and real Irish testers (including two people over 70 and one noisy place). Every P1 scenario must pass **10 out of 10** before launch. Every real failure becomes a new scenario.

| Area | Scenarios (details in the research doc, §8) |
|---|---|
| Errors | E-01 crash · E-02 credit runs out · E-03 slow calendar · E-04 timeout after a booking |
| Read-back | R-01 to R-05 (party and time, a correction, "double seven", Irish names, Eircode) |
| Loops | L-01 to L-03 |
| Made-up answers | H-01 to H-04 (Stephen's Day hours, prices, "your website says €50") |
| Transfers | T-01 to T-05 (after hours, busy, voicemail, "are you a robot") |
| Silence | SL-01 to SL-03 (the diary, total silence, an 80-year-old caller) |
| Privacy and tricks | P-01, P-02, I-01 to I-03 |
| Accents | A-01 to A-05 (Dublin, Cork, Belfast/Donegal, Midlands, non-native) |
| Restaurants | RS-01 to RS-07 (party of 12, fully booked, allergies, last table at the same moment) |
| Clinics | CL-01 to CL-07 (swelling, antibiotics, new patient, a daughter calling, chest pain) |
| Salons | SA-01 to SA-04 |
| Estate agents | EA-01 to EA-05 |
| Trades | TR-01 to TR-07 (gas, no heat for an 85-year-old, a leak, a rural Eircode, a CO alarm) |

## What to watch in the first month

| Watch | Alert when |
|---|---|
| Calls ending in a crash | Any, per business per day |
| Bookings or messages missing a detail | Over 2% |
| The same question asked 3+ times | Over 5% of calls |
| A person was asked for, but no transfer or message happened | Any |
| A transfer reached voicemail or nobody answered | Over 30% |
| Emergency triggers | Every one reviewed by a person |
| Slow replies (p95) | Over 1.5 s for 10 minutes |
| Duplicate bookings | Any |

## Decisions for the review

1. Are the emergency lines and numbers approved per industry? (Confirm the numbers on official sites first.)
2. Where do transfer hours come from: Business facts, or the calendar's opening times?
3. Does keypad entry pass through VoIPTel/Asterisk? Who checks?
4. Who records the Irish-accent test set, and which speech-to-text providers do we compare?
5. Should messages also need a read-back, as well as bookings?
6. Is the launch rule "every P1 passes 10 of 10" agreed?
