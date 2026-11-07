# Settings and notifications
<!-- pages: /settings, /settings/notifications -->

## How is Settings organised?

Open **Settings** in the left menu (under **Your agent**). It opens the first settings screen you're allowed to use. The settings menu has these groups:

- **Workspace**: **General**, **Members**, **Notifications**, **Reports by email**, **Billing**
- **Compliance**: **Privacy & compliance**
- **Developer**: **API keys**, **MCP & telemetry**
- **Account**: **Your account**

You only see the screens your role allows. For example, **General** is for Admins, and **Notifications** is for the Owner and Admins. Everyone can open [Your account](/account).
<!-- source: ui/src/components/settings/settingsNav.ts, ui/src/components/layout/navConfig.ts -->

## How do I change my workspace name?

Only an **Admin** can do this, on **Settings** > [General](/settings).

1. In the **Workspace** card, edit **Workspace name**.
2. Press **Save**. You'll see "Workspace renamed".

The name is shown to members and in invitation emails. It can be up to 100 characters.

If you're not an Admin, **General** isn't in your settings menu. Ask an Admin to rename the workspace.
<!-- source: ui/src/app/settings/page.tsx, ui/src/app/team/OrganizationNameCard.tsx, ui/src/components/settings/settingsNav.ts -->

## How do I set my timezone and test phone number?

On **Settings** > [General](/settings), the **Defaults and call reporting** card has (Admins only):

- **Timezone**: "Used for schedules and the times in reports."
- **Test phone number**: "The number test calls ring when you don't enter one."

Change them and press **Save**.

Under **Advanced** ("Most businesses can leave these off") there are two switches: **Your own phone system (PBX)**, and **Your own call outcome codes** for showing outcomes using your own codes in reports.
<!-- source: ui/src/app/settings/page.tsx, ui/src/components/OrganizationPreferencesSection.tsx -->

## Who gets emailed after calls?

On **Settings** > [Notifications](/settings/notifications), **Emails after calls** sends "One short email per call, with a link to the call." Changes save straight away.

- **Email us after calls**: the main on/off switch.
- **When a booking is made, moved or cancelled** (only changes the calendar confirmed).
- **When a message is taken**.
- **When a call is missed**.
- **Send to owners and admins**: emails everyone with the Owner or Admin role. Their addresses are listed under it.
- **Also send to**: add up to 10 more email addresses and press **Add**. Press the X on one to remove it.

Only the **Owner** and **Admins** can open Notifications. If you see "Email isn't set up on this server yet", nothing is sent for now.
<!-- source: ui/src/app/settings/notifications/page.tsx, ui/src/components/settings/settingsNav.ts, api/services/auth/permissions.py -->

## Can callers get a text confirming their booking?

Yes. On **Settings** > [Notifications](/settings/notifications), under **Texts to callers**, turn on **Text callers a booking confirmation**. The text confirms the booking with the day, time and your number.

It's only sent when the calendar confirmed the booking, and only to mobile numbers. The switch saves straight away.

If you see "Texting isn't set up yet", texts aren't sent for now. Once texting is set up, confirmations start on their own if this is on.

Only the **Owner** and **Admins** can change this.
<!-- source: ui/src/app/settings/notifications/page.tsx -->

## Can I get a summary of my calls by email?

Yes. **Settings** > [Reports by email](/settings/reports) sends "A daily, weekly or monthly summary of your calls, sent to your inbox."

Choosing which reports are emailed, and to whom, is for the **Owner** and **Admins**.

This is separate from **Notifications**, which sends one email per call. To get an email after each call instead, use [Notifications](/settings/notifications).
<!-- source: ui/src/components/settings/settingsNav.ts, api/services/auth/permissions.py -->
