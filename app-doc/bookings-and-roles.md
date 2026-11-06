# Bookings and roles: how the system works

A reference for the founders and the team. It covers who can do what in a
workspace, how the voice agent takes a booking, how a calendar's rules decide
whether a time is free, and where each part lives in the code. Last updated
2026-11-05 (PRs #145 and #146).

## 1. Roles

Every person in a workspace has one role. The stored value is on the left;
the app shows the label.

| Stored role | Shown as | Who it's for | Can |
|---|---|---|---|
| `admin` | Admin | LightMove team, or a technical admin | Everything, including members, billing and workspace settings |
| `developer` | Developer | Whoever builds the agents | Build and configure agents, telephony, integrations and API keys. **Not** booking decisions |
| `viewer` | **Owner** | The business owner | See everything (calls, bookings, reports, billing, members); switch AI booking on and off; decide which staff may too; choose who is emailed after calls |
| `staff` | **Staff** | The business's team | View only: calls, bookings, reports. The owner can let them manage bookings |

Notes:

- `viewer` was shown as "Client" before 2026-11-05. The stored value didn't
  change, so existing logins kept working and became Owners.
- Only admins invite people, change roles and remove members (`members:manage`).
- Platform superusers (`users.is_superuser`) act as Admin in any workspace
  for support. That's separate from workspace roles.

### Booking rights

| | View bookings | Switch AI booking on/off | Let a staff member manage bookings |
|---|---|---|---|
| Owner | ✓ | ✓ | ✓ |
| Admin | ✓ | ✓ | ✓ |
| Staff | ✓ | only if allowed | — |
| Developer | ✓ | — | — |

**"Can manage bookings"** is a switch on each staff member's row on the
Team page:

- The Owner or an Admin flips it. Staff can see it but can't change it.
- It's stored on the membership (`organization_users.can_manage_bookings`)
  and only ever applies to Staff. For other roles the flag is ignored.

### How it's enforced

- **Permissions.** Each role maps to a set of permissions in
  `api/services/auth/permissions.py` (`ROLE_PERMISSIONS`). The two booking
  permissions are:
  - `bookings:manage`: switch AI booking on a calendar;
  - `bookings:grant`: change a staff member's "Can manage bookings".

  Owners and admins also hold `notifications:manage` (Settings →
  Notifications, see `app-doc/notifications.md`).
- **The switch as a permission.** `member_grants()` turns a staff member's
  switch into `bookings:manage`. The membership is read once per request,
  with the role (`get_member_access`), and `OrgMembership.can()` checks the
  role's permissions plus these grants.
- **What the UI sees.** `/api/v1/organizations/context` returns the same
  combined list, and the UI's `can()` (`OrgConfigContext`) hides what a
  person can't do. The API checks again on every request, so hiding a button
  is never the only protection.
- **Tests.** `api/tests/test_route_permissions.py` checks every route
  against every role, and `api/tests/test_bookings_access.py` covers the
  booking rules.

## 2. How a booking happens

```
Caller ──► Voice agent (failte-ai API, pipecat)
              │  MCP tool calls, with the connection's key
              ▼
           Tools service (failte-ai/tools, "fallcha-tools")
              │  Google Calendar API, as the workspace's service account or OAuth sign-in
              ▼
           The business's Google Calendar
```

1. **Setup.** An admin connects Google Calendar under **Integrations**. Each
   workspace has its own connection: one calendar per demo or per business.
2. **Agent creation.** The setup wizard asks what else the agent should ask
   when someone books, as **toggle buttons**. For example, a restaurant
   gets party size and allergies on by default; occasion, seating and high
   chair off. Day, time, name and phone number are always asked. The
   choices become one sentence in the agent's instructions.
3. **On the call**, every booking agent follows the same steps:
   1. Ask for the details, one at a time, skipping anything the caller
      already said.
   2. Call `check_appointment_availability` (day, part of day, party size).
      Offer only the times it returns.
   3. Read the booking back in one sentence and wait for a yes.
   4. Call `book_appointment`, then confirm the time the calendar gave.
4. **Hand-offs.** If a tool answers with `handoff`, the agent reads the
   tool's line, then transfers the caller or takes a message. It never
   tells a caller they're booked unless the calendar confirmed it.

   | `handoff` | When |
   |---|---|
   | `booking_off` | The owner switched AI booking off for that calendar |
   | `party_too_large` / `party_too_small` | Outside the party sizes the agent may book |
   | `fully_booked` | Nothing free in the whole booking window |
   | `changes_off` | The owner hasn't let the agent cancel or move bookings |
   | `booking_not_found` | No upcoming booking matched the caller's number and name/day |

   If the tool says `needs_party_size`, the agent asks how many people and
   checks again.
5. **Cancelling or moving a booking made on an earlier call.** This only
   happens if the owner switched on **"Let the agent cancel or move bookings"**
   for that calendar (off by default):
   1. The agent asks for the phone number the booking was made under, plus
      the name or the day of the booking.
   2. `find_booking` returns only upcoming bookings this agent made where the
      number matches (last 9 digits, so "087…" and "+353 87…" agree) and so
      does the name (any shared word) or the day.
   3. The agent reads the booking back and gets a yes, then calls
      `cancel_appointment` or `move_appointment`. Moving books the new time
      before removing the old one.

   If the switch is off (`changes_off`) or nothing matches
   (`booking_not_found`), the agent changes nothing and transfers the
   caller or takes a message. A booking made earlier on the same call can
   always be cancelled.
6. **Afterwards.** The booking is an event on the calendar ("Table for 4 —
   Mary Byrne", with the caller's number and party size). Each call also
   records `booking_outcome`, `booking_date`, `booking_time` and the
   industry's details (party size, service, property…).

## 3. Calendar booking rules

These are set per calendar connection. The defaults are a one-person diary:
one booking at a time, decided by Google free/busy, so any Busy event blocks
its time. That suits a clinic or a salon chair, and is how it always worked.

Setting any capacity rule switches the calendar to **counting** its events:

| Setting | What it means | Example |
|---|---|---|
| `ai_booking_enabled` | Owner's on/off switch | Off on a bank holiday |
| `ai_changes_enabled` | Owner's switch: may the agent cancel or move earlier bookings (after checking the caller) | Off by default |
| `service_periods` | When bookings may start, per weekday | Lunch 12:00–14:00, dinner 17:00–21:00, Thu–Sat |
| `slot_minutes` | Gap between start times | 15 or 30 |
| `booking_minutes` | How long a booking holds a table | 90 for dinner |
| `buffer_minutes` | Reset time after a booking | 15 |
| `max_bookings_at_once` | Tables released for phone bookings (max 500) | 5 of 20; the rest are for walk-ins |
| `max_guests_at_once` | Covers seated at the same moment | 40 |
| `max_guests_per_start` | Covers arriving at one time (kitchen pacing) | 12 |
| `min_party_size` / `max_party_size` | Groups outside these go to a person | max 8 |
| `min_lead_hours` / `horizon_days` | How soon, and how far ahead | 1 hour, 14 days |

### How the calendar is read when counting

- **The agent's own bookings** count with their stored party size.
- **Events staff add by hand** count as bookings when the title names a party
  size: "Table for 4", "Party of 6", "Murphy 3 pax", "8 guests". This is how
  walk-ins or phone bookings taken by staff use up a table.
- **Any other Busy event** ("Private party", "Staff training") closes its
  time.
- **Free events** are ignored, except an all-day event whose title says
  "Closed", which closes the day. Google shows all-day events as Free unless
  told otherwise.

A time fits when, at the busiest moment of the new booking's stay, the
bookings and covers stay within the limits. A table freed at 18:30 can be
sold again at 18:30.

**Two callers going for the last table.** Bookings for one calendar are taken
one at a time within a server. Across servers, each booking re-reads the
calendar after it is written:

- If bookings made earlier already fill the time, the later one removes
  itself and offers other times.
- Every server sorts the same way (Google's creation time, then id), so
  exactly one keeps the table.
- If the re-read fails, the booking is kept and a warning is logged, rather
  than dropping a real booking.

## 4. The Bookings page

`/bookings` in the app:

- **Who sees it:** anyone who can see calls (Owner, Staff, Developer, Admin).
- **What it shows:**
  - bookings read live from each connected calendar, grouped by day;
  - time, name, party size (or "Not asked"), tap-to-call number and reason;
  - cancelled bookings hidden unless "Show cancelled" is on.
- **The switches:** each calendar has **"Let the agent book"** and **"Let
  the agent cancel or move bookings"** for anyone with `bookings:manage`.
  They change only those two settings, and only on a booking calendar,
  through `PUT /api/v1/integrations/bookings/calendars/{id}`.
- **Errors:** a calendar that can't be read shows why (e.g. "make sure it is
  shared with …"), and the others still load.

### Booking rules panel
Each calendar on the Bookings page has **Booking rules**:
- everyone sees a one-line summary ("5 bookings at the same time · 90 min each · groups up to 8");
- the owner (or an admin, or staff allowed to manage bookings) can edit:
  - start from a preset (**Appointments** or **Restaurant tables**);
  - set opening times as day buttons with first and last booking times;
  - adjust bookings at the same time, largest group, most guests, booking length, gap between start times, reset time, minimum notice and days ahead.

Saving goes through the same narrow endpoint as the switches. It accepts
only these rule keys, never the calendar id, and the tools service checks the
combination.

## 5. Where things live

| Part | Code |
|---|---|
| Roles and permissions | `api/enums.py` (`OrgRole`), `api/services/auth/permissions.py`, `api/services/auth/depends.py` |
| Membership storage | `organization_users` (`role`, `can_manage_bookings`); migration `b7c1d2e3f4a5` |
| Team page switch | `api/routes/team.py` (`PUT /organizations/members/{id}/bookings-access`), `ui/src/app/team/MembersCard.tsx` |
| Booking rules and counting | `tools/fallcha_tools/providers/google_calendar/` (`settings.py`, `scheduling.py`, `service.py`); see `tools/README.md` "Booking rules" |
| Agent tools | `tools/fallcha_tools/providers/google_calendar/tools.py` (`check_appointment_availability`, `book_appointment`, `find_booking`, `move_appointment`, `cancel_appointment`) |
| Bookings list | tools `GET /internal/connections/{id}/bookings`; API `GET /api/v1/integrations/bookings`; UI `ui/src/app/bookings/` |
| Booking questions (toggles) | `api/services/workflow/starter_templates.py` (`_booking_steps`, `*_TOGGLES`), `api/services/workflow/template_setup.py` (`toggles_answer`), `ui/src/components/workflow/create/TemplateSetup.tsx` |

## 6. Known gaps

- Clearing an optional limit (largest group, most guests) back to "no limit"
  from the Booking rules panel isn't possible yet; the field keeps its value.
- Booking confirmations by text are built but wait for an SMS provider and
  the LightMove number; the business is emailed after calls today. See
  `app-doc/notifications.md`.
- Choosing a particular stylist or practitioner, and appointment types of
  different lengths, are not supported. "Bookings at once" covers several
  chairs or rooms without choosing who.
- Not yet tested against a real Google Calendar end to end. Demo calendars
  are being set up.
