# Reports
<!-- pages: /reports -->

## What does the Reports screen show?

**Reports** shows "your business in numbers": how your phone agent did, as cards of numbers and charts.

- **On a computer:** choose **Reports** in the left menu.
- **On a phone:** tap **More** in the bottom tab bar, then **Reports**.

The heading names the period, for example "Last 7 days, 1–7 Nov", and what it is "Compared with". The top row has headline numbers such as **Calls answered**. Below are cards such as **What callers wanted, day by day**, **Busiest times**, **Questions your agent couldn't answer**, **Follow-ups**, **Calls while you were closed** and **How your agent did**.

Everyone on the team can see Reports. Times are shown in your business's time zone.

Open it here: [Reports](/reports).
<!-- source: ui/src/app/reports/page.tsx, ui/src/app/reports/reportView.ts, api/services/report_cards/catalogue.py, ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx -->

## What is a report pack?

Each report on the **Reports** screen starts from a pack of cards suited to your kind of business. The label at the top says which, for example "Reports · Restaurant pack".

The pack comes from the ready-made agent you started from:

- **Restaurant**: adds cards such as **Bookings taken**, **Covers booked**, **Tables you couldn't fit**, **Takeaway orders**, **Which days are filling up** and **Special requests**.
- **Dental / GP clinic**: **Appointments booked**, **Emergencies**, **Cancellations and moves**, **New and existing patients**, **Appointment types**.
- **Trades**: **Jobs and quotes requested**, **After-hours call-outs**, **Callbacks still waiting**, **Emergencies by hour**, **Where calls come from**.
- **VoIP / support line**: **Sorted by your agent**, **Passed to your team**, **Issues by type**, **Waiting for your team**, **Call spikes by hour**, **Repeat callers**.
- **Standard**: the shared cards, for every other kind of business.

When **All agents** is chosen, the pack follows your first switched-on agent.
<!-- source: api/services/report_cards/catalogue.py, api/services/report_cards/service.py, ui/src/app/reports/page.tsx -->

## How do I change the period or agent on Reports?

At the top right of the **Reports** screen:

1. Pick **Today**, **7 days**, **30 days** or **Custom**. For **Custom**, choose the first and last day on the calendar and press **Show**.
2. If you have more than one agent, use the agent menu to pick one, or **All agents**.

Numbers are compared with the period just before (for **Today**, the same time last week on that weekday).

To get the calls behind the report, press **Download**. You get a spreadsheet of the calls in that period, with the time, agent, caller, outcome, reason, length and a link to each call.

If there were no calls, you'll see "No calls in this period. Try a longer period, or another agent."
<!-- source: ui/src/app/reports/page.tsx, ui/src/app/reports/reportView.ts, ui/src/app/reports/csv.ts -->

## How do I customise which cards show on Reports?

On the **Reports** screen, press **Customise**. The **Customise this report** panel opens.

1. **Show or hide** a card with the switch on its row.
2. **Reorder** cards by dragging them by the handle. On a keyboard, focus a handle and use the up and down arrow keys.
3. **Pick email cards**: tick **in email** for each card you want in your emailed reports.
4. Press **Save**. You'll see "Report saved. Everyone in your business sees it this way."

To start again, press **Reset to the … pack** (for example **Reset to the Restaurant pack**).

Only the **Owner** or an **Admin** sees **Customise**. The layout is saved for the whole business, so you and your staff see the same report. If you switch every card off, the page says "Every card is switched off".
<!-- source: ui/src/app/reports/components/CustomiseDrawer.tsx, ui/src/app/reports/page.tsx, api/routes/report_cards.py, api/services/report_cards/layout.py, api/services/auth/permissions.py -->

## How do the money estimates on Reports work?

Some packs on the **Reports** screen have a money card: **Bookings value** (Restaurant), **Appointments value** (Dental / GP clinic) or **Jobs value** (Trades). LightMove doesn't know your prices, so these only appear once you give your own average.

1. On **Reports**, press **Customise**.
2. Fill in the box, for example **Average spend per cover**, **Average value per appointment** or **Average value per job**, in euro.
3. Press **Save**.

The card is then labelled **Estimate** and shows the sum written out, for example "Estimate: 142 covers × your €35 average spend". Leave the box empty to show no money at all. The amount must be more than €0 and no more than €100,000.

Only the **Owner** or an **Admin** can set the average.
<!-- source: ui/src/app/reports/components/CustomiseDrawer.tsx, ui/src/app/reports/components/ReportCard.tsx, ui/src/app/reports/reportView.ts, api/services/report_cards/catalogue.py, api/services/report_cards/layout.py -->

## Can I answer a question from the Reports screen?

Yes. On the **Reports** screen, the **Questions your agent couldn't answer** card lists questions callers asked that your agent didn't know. The **Owner**, an **Admin** or a **Developer** can answer them there.

1. Press **Add an answer** next to a question.
2. Type **Your answer** and press **Save answer**.

Your agent uses it from its next call, and the matching follow-up is marked done.

You can also add answers from [Follow-ups](/follow-ups) or on [What your agent knows](/workflow/{agent}/facts).
<!-- source: ui/src/app/reports/page.tsx, ui/src/app/reports/components/ReportCard.tsx, ui/src/components/dashboard/AddAnswerDialog.tsx, api/services/auth/permissions.py -->

## How do I get the report by email?

At the bottom of the **Reports** screen, press **Get this report by email**. It takes you to **Settings > Reports by email**, where you choose daily, weekly or monthly reports and who gets them.

The email includes the cards ticked **in email** under **Customise**, in the same order as on the page.

Open it here: [Reports by email](/settings/reports).
<!-- source: ui/src/app/reports/page.tsx, ui/src/app/reports/components/CustomiseDrawer.tsx, api/services/email_reports/cards.py -->
