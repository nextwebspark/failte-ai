# Privacy and your data
<!-- pages: /settings/compliance, /account, /usage -->

## Where are the privacy settings?

Privacy is on **Settings** > **Privacy & compliance**. Open **Settings** in the left menu, or go to [Privacy & compliance](/settings/compliance).

It covers "How long call data is kept, what callers are told, and how to answer data requests." The sections are:
- **Data retention**
- **AI and recording notice**
- **Caller data requests**
- **Legal documents** (Privacy Policy, Terms of Service, Data Processing Agreement, Sub-processors, Cookie Policy)
- **Danger zone** (Admins only)

Every role can open this screen, but only an **Admin** can change retention, answer caller data requests, or export or delete the workspace.
<!-- source: ui/src/app/settings/compliance/page.tsx, ui/src/components/settings/settingsNav.ts -->

## How long are call recordings and transcripts kept?

On [Privacy & compliance](/settings/compliance), **Data retention** shows how long recordings, transcripts and call details are kept. The default is **90 days**. After that they are permanently deleted. Billing details (duration, cost, status) are kept.

To change it (**Admin** only):
1. In **Call data retention (days)**, enter a whole number from 1 to 365.
2. Press **Save**.

If you shorten it, you're asked "Shorten call data retention?". Anything older than the new period is deleted for good at the next daily cleanup. Press **Shorten and save** to confirm.

Other roles see the period with "Only an admin can change it."
<!-- source: ui/src/app/settings/compliance/page.tsx, ui/src/components/OrganizationPreferencesSection.tsx -->

## What are callers told at the start of a call?

On [Privacy & compliance](/settings/compliance), **AI and recording notice** shows each active agent. At the start of a call, an agent can tell the caller they are speaking with an AI and that the call may be recorded.

Each agent shows **On** or **Off**, and whether it "Speaks the notice in the agent's voice" or "Plays a recorded notice". New agents play the notice unless you turn it off. If some are off, you'll see a reminder to turn it back on unless callers are told another way.

To change it, press **Edit** next to the agent. This opens the agent's [Settings](/workflow/{agent}/settings). A change takes effect on calls once the agent is published.
<!-- source: ui/src/app/settings/compliance/AgentDisclosureList.tsx, ui/src/app/settings/compliance/page.tsx -->

## A caller wants a copy of their data, or wants it deleted. What do I do?

Only an **Admin** can do this. It's under **Caller data requests** on [Privacy & compliance](/settings/compliance), and also on [Calls](/usage) ("A caller wants their data").

1. Press **Caller data request**.
2. Enter the caller's phone number in international format (+ and the country code).
3. To give them a copy, press **Download data (JSON)**. Recording links in the file expire after one hour.
4. To delete, press **Erase all data** and confirm.

Erasing deletes recordings, transcripts, call details and the number from every call with that number, across all your agents. Calls stay in your usage history with date, duration, status and cost for billing. It can't be undone.
<!-- source: ui/src/components/privacy/CallerDataRequestDialog.tsx, ui/src/app/settings/compliance/page.tsx, ui/src/app/usage/page.tsx -->

## How do I delete the data from one call?

Only an **Admin** can do this.

1. Open the call from [Calls](/usage). In the call panel, open **Technical details** and press **Open full page**.
2. Press **Delete call data**.
3. Confirm "Delete this call's data?".

The recording, transcript, phone numbers, call context and QA results of that call are deleted for good. The call stays in your usage history with its date, duration, status and cost, because billing records refer to it.

To delete everything for one caller instead, use **Caller data request** on [Privacy & compliance](/settings/compliance).
<!-- source: ui/src/components/privacy/DeleteCallDataButton.tsx, ui/src/app/workflow/[workflowId]/run/[runId]/page.tsx, ui/src/app/usage/CallPanel.tsx -->

## How do I export or delete my own account?

Anyone can do this on **Settings** > [Your account](/account).

- **Export my data**: downloads your profile, organization memberships and roles as a JSON file.
- **Delete my account**: "Signs you out everywhere and deletes your account." Agents and other work you created stay with your workspaces. Type your email to confirm. This cannot be undone.

If you are the only Admin of a workspace that has other members, you must first make another member an Admin on [Members](/team), or delete the workspace.
<!-- source: ui/src/components/privacy/YourAccountCard.tsx, ui/src/app/account/page.tsx, api/errors/privacy.py -->

## How do I export all my workspace's data?

Only an **Admin** can do this, in **Danger zone** at the bottom of [Privacy & compliance](/settings/compliance).

Under **Export organization data**, press **Export**. You get a JSON file with settings, members, agents, tools, campaigns, knowledge base files, phone numbers and the billing ledger. Secrets and call recordings are not included.

To get one caller's calls, use **Caller data request** on the same screen instead.
<!-- source: ui/src/components/privacy/DangerZoneCard.tsx, ui/src/app/settings/compliance/page.tsx -->

## How do I delete my whole workspace?

Only an **Admin** can delete the workspace, in **Danger zone** on [Privacy & compliance](/settings/compliance).

1. Press **Delete organization**.
2. Type the workspace name to confirm, then press **Delete organization**.

The workspace closes straight away: agents stop taking calls, and API keys, widgets and running campaigns are switched off. After **30 days**, agents, call recordings, transcripts, contacts and everything else are permanently erased. Billing records are kept as the law requires.

Until then an Admin can press **Cancel deletion**. Export your data first if you need it.
<!-- source: ui/src/components/privacy/DeleteOrganizationDialog.tsx, ui/src/components/privacy/DangerZoneCard.tsx, ui/src/components/privacy/PendingDeletionBanner.tsx -->
