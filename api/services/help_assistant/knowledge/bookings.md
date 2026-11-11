# Bookings
<!-- pages: /bookings -->

## What does the Bookings screen show?

**Bookings** shows the tables and appointments your agent booked, day by day.

- **On a computer:** choose **Bookings** in the left menu.
- **On a phone:** tap **More** in the bottom tab bar, then **Bookings**.

At the top, pick **Next 7 days**, **Next 14 days** or **Last 7 days**. A line sums it up, for example "3 bookings · 9 guests · 1 cancelled".

Each booking shows the time, the caller's name (or "Name not given"), **Booked** or **Cancelled**, the party size (or "Not asked"), the phone number, and "Booked by your agent on …". If cancelled bookings exist, switch on **Show cancelled** to see them.

Everyone on the team can see this screen.

Open it here: [Bookings](/bookings).
<!-- source: ui/src/app/bookings/page.tsx, ui/src/app/bookings/BookingDays.tsx, ui/src/app/bookings/bookingsView.ts, ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx -->

## Where do bookings come from?

The **Bookings** screen lists "bookings your agent took on the phone, read live from your calendar". Bookings your team adds straight into the calendar aren't listed.

For this to work, a calendar must be connected. If none is, the screen says **Connect your calendar to take bookings**: link your **Google Calendar** or **Calendly** and your agent can offer callers real free times and book them while they're still on the line.

To connect one:

1. Press **Connect a calendar**, or go to [Integrations](/integrations) (under **Advanced setup** in the left menu).
2. Follow the steps to link your calendar.

Connecting a calendar needs an **Admin** or **Developer**. Others see "Ask an admin on your team to connect it."
<!-- source: ui/src/app/bookings/page.tsx, ui/src/components/layout/navConfig.ts, api/services/auth/permissions.py -->

## How do I turn my agent's booking on or off?

On the **Bookings** screen, each connected calendar has a card under **Your calendar** (or **Your calendars**). Its pill says **Agent books** or **Booking off**.

- Switch **Let the agent book** on or off. When off, "your agent won't book on this calendar. Callers who want a booking are passed to your team, or their details are taken for a call back."
- Switch **Let the agent cancel or move bookings** on or off. Your agent only does this after the caller gives the phone number the booking was made under, plus their name or the day of the booking. If anything doesn't match, or this is off, the caller is passed to your team or a message is taken.

For **Calendly**, your agent can't move or cancel bookings. Callers use the links in their Calendly email, or you change them in Calendly.
<!-- source: ui/src/app/bookings/page.tsx -->

## How do I set booking rules?

On the **Bookings** screen, each calendar card (except Calendly) shows **Booking rules** with a summary such as "One booking at a time · 30 min each · up to 14 days ahead".

1. Press **Edit booking rules**.
2. Under **Start from**, pick **Appointments** or **Restaurant tables** to fill in typical rules (this replaces the rules below).
3. Under **When bookings can start**, pick days and the **First** and **Last** start times. Press **Add opening times** for more.
4. Set numbers such as **Bookings at the same time**, **Largest group the agent may book**, **How long a booking lasts (minutes)**, **Gap between start times (minutes)**, **Reset time between bookings (minutes)**, **Minimum notice (hours)** and **Book up to (days ahead)**.
5. Press **Save booking rules**.

Your agent uses them from the next call. Calendly keeps its own hours and rules, so change those in Calendly.
<!-- source: ui/src/app/bookings/page.tsx, ui/src/app/bookings/BookingRules.tsx -->

## Who can manage bookings?

On the **Bookings** screen, everyone can see bookings. Changing **Let the agent book**, **Let the agent cancel or move bookings** and **Booking rules** is for:

- the **Owner**;
- an **Admin**;
- a **Staff** member the Owner or an Admin has allowed.

A **Developer** can't change these booking settings.

To let a staff member manage bookings:

1. Open **Settings**, then **Members** ([Members](/team)).
2. Next to the staff member, switch on **Can manage bookings**.

Only the Owner or an Admin can switch this on or off.
<!-- source: api/services/auth/permissions.py, ui/src/lib/auth/roles.ts, ui/src/app/bookings/page.tsx, ui/src/app/team/MembersCard.tsx, ui/src/components/settings/settingsNav.ts -->

## Why does Bookings say it couldn't read my calendar?

If a calendar card on the **Bookings** screen says "Couldn't read this calendar", your agent can't offer times from it until the connection is fixed.

- If you can see Integrations, press **Check the connection** to go to [Integrations](/integrations) and reconnect it.
- Otherwise, ask an Admin on your team to check the calendar connection.

Other messages you might see:

- **Bookings aren't switched on for your account yet**: ask your LightMove contact to turn them on.
- **Bookings aren't available right now**: try again in a minute with **Try again**.
<!-- source: ui/src/app/bookings/page.tsx, ui/src/app/bookings/bookingsView.ts -->
