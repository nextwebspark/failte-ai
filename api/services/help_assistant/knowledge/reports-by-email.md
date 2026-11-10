# Reports by email
<!-- pages: /settings/reports -->

## How do I get call reports by email?

**Reports by email** sends "a summary of your calls: how many, how they went and who needs a call back".

To find it:

- **On a computer:** choose **Settings** in the left menu (under **Your agent**), then **Reports by email**.
- **On a phone:** tap **More** in the bottom tab bar, then **Settings**, then **Reports by email**.
- Or press **Get this report by email** at the bottom of the **Reports** screen.

Under **Which reports**, switch on any of:

1. **Daily**: the last 24 hours of calls, from your send time the day before up to your send time today, so calls in the evening are in the next day's report. Arrives every day at that time. Change it with **Send at**.
2. **Weekly**: last week's calls, Monday to Sunday. Arrives Mondays at 8 am.
3. **Monthly**: last month's calls. Arrives on the 1st at 8 am.

Times are in your business's time zone. Each shows **Last sent** once one has gone out.

Open it here: [Reports by email](/settings/reports).
<!-- source: ui/src/app/settings/reports/page.tsx, ui/src/app/settings/reports/reportCopy.ts, ui/src/components/settings/settingsNav.ts, ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx, ui/src/app/reports/page.tsx -->

## How do I choose who gets the email reports?

On **Settings > Reports by email**, go to **Who gets them**.

1. Press **Add my email** to add your own sign-in address. It starts getting reports straight away.
2. To add someone else, type their address under **Add another email** and press **Add**.
3. They get an email with a link to confirm. Their row says **Waiting for confirmation** until they do, then **Getting reports**. Nothing is sent to them until they confirm.
4. The link works for 48 hours. If it expired or got lost, press **Resend**.
5. To stop sending to someone, press **Remove**.

You can add up to 10 addresses.

The person confirming sees **Get call reports by email** and presses **Yes, send me reports**. If they weren't expecting it, they can close the page and nothing is sent.
<!-- source: ui/src/app/settings/reports/page.tsx, ui/src/app/settings/reports/reportCopy.ts, ui/src/app/reports/confirm/[token]/ConfirmReports.tsx, api/services/email_reports/settings.py, api/services/email_reports/tokens.py -->

## Can I report on just one agent?

Yes. If you have more than one agent, **Settings > Reports by email** shows a **Calls to** menu under **Which reports**. Pick one agent, or **All agents**.

The email shows the report cards ticked **in email** on the **Reports** screen. To change which cards go in, open [Reports](/reports), press **Customise**, and tick or untick **in email** for each card.
<!-- source: ui/src/app/settings/reports/page.tsx, ui/src/app/reports/components/CustomiseDrawer.tsx, api/services/email_reports/cards.py -->

## How do I preview or test the report email?

On **Settings > Reports by email**, go to **Preview**.

1. Press **Daily**, **Weekly** or **Monthly** to see the email with your real calls: today so far for daily, the last full week or month otherwise.
2. Press **Send me a test now** to send that report to your own address only. The note under the button shows where it goes.

Everyone who can see reports can preview and send themselves a test, even if they can't change the settings.

If you see "Email isn't set up on this server yet, so nothing is sent for now.", report emails can't be sent yet, even if they are switched on.
<!-- source: ui/src/app/settings/reports/page.tsx -->

## Who can change the email report settings?

On **Settings > Reports by email**, only the **Owner** or an **Admin** can switch reports on or off, change the send time, pick the agent, and add or remove addresses.

Everyone else (**Developer** and **Staff**) sees: "You can see these settings, preview the email and send yourself a test. Only the workspace owner or an admin can change who gets reports."
<!-- source: ui/src/app/settings/reports/page.tsx, api/services/auth/permissions.py, ui/src/lib/auth/roles.ts -->

## How do I unsubscribe from the email reports?

Every report email has an **Unsubscribe** link at the bottom. Opening it unsubscribes that address straight away; the page says **You're unsubscribed**.

To get reports again, ask the workspace owner to add you again on **Settings > Reports by email**.

If the page says **This link doesn't work**, use the **Unsubscribe** link in the latest report, or ask the workspace owner to remove you.

The Owner or an Admin can also remove anyone by pressing **Remove** next to their address under **Who gets them**.

Manage it here: [Reports by email](/settings/reports).
<!-- source: ui/src/app/reports/unsubscribe/[token]/Unsubscribe.tsx, ui/src/app/reports/confirm/[token]/ConfirmReports.tsx, ui/src/app/settings/reports/page.tsx -->
