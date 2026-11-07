# Home
<!-- pages: /overview, /workflow/{agent}/home -->

## What is the Home screen?

**Home** is where everyone lands after signing in. It shows how your phone agent did, what needs you, and when people called. Every number is counted from your real calls.

- **On a computer:** choose **Home** at the top of the left menu.
- **On a phone:** tap **Home** in the bottom tab bar.

At the top you see a greeting, a line such as "Here's how your phone agent did today", and a short "at a glance" row (calls, handled by your agent, bookings, callbacks). A pill shows **Answering calls** with your number, or **Not answering**.

Use the switch at the top right to pick **Today**, **7 days** or **30 days**. Everything on Home changes to match.

Each agent also has its own version of this screen, showing only that agent's calls: [your agent's home](/workflow/{agent}/home).

Open it here: [Home](/overview).
<!-- source: ui/src/app/overview/page.tsx, ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/dashboardView.ts, ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx, ui/src/app/workflow/[workflowId]/home/page.tsx -->

## What do the four number tiles on Home mean?

The row of tiles near the top of **Home** counts your calls for the period you picked (**Today**, **7 days** or **30 days**):

1. **Calls today** (or **Calls**): how many calls came in. Underneath you may see the change compared with the same day last week, or the 7 or 30 days before.
2. **Handled by your agent**: calls "answered start to finish, no staff needed", with the share as a percentage.
3. **Passed to your team**: calls your agent put through to a person. It shows how many were picked up and how many were **not answered**.
4. **Hung up without speaking**: callers who rang off before saying anything.

If you have no calls yet, Home shows setup steps instead of the tiles.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/dashboardView.ts -->

## What is "Needs your attention" on Home?

The **Needs your attention** card on **Home** lists up to four callers who are waiting on a person, with a count of everything still open. These are the same items as the **Follow-ups** screen: callback requests, transfers nobody answered, people who rang more than once, questions your agent couldn't answer, and times that were full.

- Press **All follow-ups** to see the full list.
- For a question your agent couldn't answer, press **Add answer** to teach your agent (Owner, Admin or Developer).
- For "couldn't answer" and "time was full" items you can press **Mark done** right on Home. Callback-type items are marked done on the Follow-ups screen.

When nothing is waiting you see **All caught up**.

See them all: [Follow-ups](/follow-ups).
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/FollowUpRow.tsx, ui/src/components/dashboard/AddAnswerDialog.tsx, api/services/auth/permissions.py -->

## What do "What callers wanted" and "When people called" show on Home?

Two chart cards on **Home** explain your calls for the chosen period:

- **What callers wanted** groups calls by the reason the caller rang (for example reservations or questions). Below it you may see how many bookings were taken and the **average call** length.
- **When people called** shows calls per hour, with your **Busiest hour** called out.

Under the hours chart, Home can also tell you how many calls "came in outside opening hours". This only works when your agent's opening hours are set as times. If they aren't, you see a note asking you to set them, and the Owner, Admin or Developer may see a **Set the hours** link to [What your agent knows](/workflow/{agent}/facts).
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/dashboardView.ts -->

## What are "Recent calls" and the "Your agent" card on Home?

**Recent calls** on **Home** lists your latest calls: who rang, what happened, the outcome (for example **Booking made**, **Callback requested**, **Passed to your team**) and the time. Press the play button to listen, or the caller's name to open the call. **All calls** takes you to the [Calls](/usage) screen.

The **Your agent** card shows:

- whether it is **Answering calls** or **Not answering**, and your phone number (or **No number linked**);
- **Last call**: when it last took a call;
- **Credit left**, with roughly how many minutes of calls that covers, when shown for your account.

If credit is running low you see "Credit is running low. Calls stop when it runs out." with a **Top up** link to [Billing](/billing). Press **Try your agent** to talk to it in your browser.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/dashboardView.ts -->

## Why does Home say "Your agent isn't answering"?

A red banner on **Home** explains why calls aren't being answered, with a button to fix it:

- **Credit has run out**: calls can't start. Press **Top up credit** ([Billing](/billing)).
- **Phone number is switched off**: press **Check your number**.
- **Agent is switched off**: press **Open your agents** ([Voice agents](/workflow)).
- **No phone number linked**: press **Link a number**.
- **No phone agent yet**: press **Create your agent** ([create one](/workflow/create)).

The banner also says when the last call was. If your role can't make the fix, the banner says "Ask the owner of your account to fix this." instead of showing the button.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/dashboardView.ts -->

## What does Home show before my first call?

Until your agent has taken a call, **Home** shows a **Let's get your first call in** card with three steps, ticked off as you go:

1. **Create your phone agent**
2. **Link your phone number**
3. **Take your first call**

If your number is linked and answering, it says **Ring your number now**: call it from your mobile and talk to your agent like a customer would. The call then shows up on Home straight away. On a phone there is a **Ring** button that opens your dialler.

If there is no working number yet, you can press **Try your agent** to talk to it in your browser instead. Browser test calls don't count on Home.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx -->

## What are the quick links at the bottom of Home?

At the bottom of **Home** there are shortcut tiles:

- **Listen to calls**: every recording, newest first, on the [Calls](/usage) screen.
- **Read transcripts**: what callers said, word for word, also on [Calls](/usage).
- **Opening hours & what it says**: change what your agent tells callers, on [What your agent knows](/workflow/{agent}/facts).
- **Try your agent**: talk to it in your browser.

The first two show for everyone who can see calls. The last two show once you have an agent.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx -->
