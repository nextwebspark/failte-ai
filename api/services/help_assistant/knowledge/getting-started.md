# Getting started
<!-- pages: /overview, /workflow, /workflow/create, /workflow/{agent}/home, /workflow/{agent}/facts, /workflow/{agent}/deployment, /integrations, /bookings -->

## What do I need to set up before my agent takes calls?

A short checklist for a new workspace:

1. **Create your agent** on [New voice agent](/workflow/create).
2. **Fill in what your agent knows**: your opening hours, address and answers, on [What your agent knows](/workflow/{agent}/facts).
3. **Try it** in your browser.
4. **Connect a phone number** so callers can reach it, on [Phone number](/workflow/{agent}/deployment).
5. **Pass calls to your team**: add a number for callers who want a person.
6. **Connect a calendar** if you want your agent to take bookings, on [Integrations](/integrations).

[Home](/overview) shows "Let's get your first call in" with the steps you still need until your agent answers its first call.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/workflow/AgentSetupChecklist.tsx, ui/src/app/workflow/[workflowId]/facts/page.tsx -->

## How do I create my agent?

1. Go to [New voice agent](/workflow/create). From [Home](/overview) you can also press **Create your agent**.
2. Under "What should your agent do?", pick a ready-made agent for your kind of business, preview it, then personalise it with your details.
3. Or choose **Describe it in your own words →**, say whether it answers calls or makes calls, and write what it should do. It takes about 20 seconds to build.
4. Or choose **Start from scratch**.

You can change any of this later. Creating agents is for the **Admin** and **Developer** roles.
<!-- source: ui/src/components/workflow/CreateAgentWizard.tsx, ui/src/components/workflow/create/TemplateGallery.tsx, ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/layout/navConfig.ts -->

## How do I fill in what my agent knows?

Open **What your agent knows** from the left menu under **Your agent**, or go to [What your agent knows](/workflow/{agent}/facts).

Fill in **Your business** (such as address and opening hours) and **Answers to common questions**, then press **Save changes**. Your agent uses them from its next call.

The **Ready to take calls** card on that page shows what's still missing, such as "No phone number linked yet" or "Calendar not connected".

The **Owner**, **Admin** and **Developer** roles can change these. **Staff** can only view them.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/components/layout/navConfig.ts, api/services/auth/permissions.py -->

## How do I try my agent before real callers ring?

You can talk to your agent in your browser.

- On [Home](/overview), press **Try your agent** ("Talk to it in your browser").
- Or open your agent's home at [Your agent](/workflow/{agent}/home) and use **Talk to your agent** in the setup steps.

Test calls don't count on the Home dashboard. Once you have a phone number, Home also suggests "Ring your number now": call it from your mobile and talk to your agent like a customer would.
<!-- source: ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/workflow/AgentSetupChecklist.tsx, ui/src/components/workflow/agentLinks.ts -->

## How do I connect a phone number?

Open **Phone number** in the left menu under **Your agent**, or go to [Phone number](/workflow/{agent}/deployment). It asks "How should callers reach" your agent:

- **Keep my existing number** (most common): callers ring the number they know, and you forward it to your agent.
- **Get a new number**: a new local number just for your agent.
- **My mobile is my business number**: forward your mobile when you're busy or don't answer.

Follow the steps, then **Check it works**: ring the number, and the step turns green when your agent answers.

Setting up numbers is for **Admins** and **Developers**. Others see "Ask a workspace admin to set up a phone number for this agent."
<!-- source: ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx, ui/src/app/workflow/[workflowId]/deployment/phoneForwarding.ts, ui/src/components/layout/navConfig.ts -->

## How do I pass calls to my team?

On [What your agent knows](/workflow/{agent}/facts), find **What your agent can do** and then **Pass calls to your team**.

1. Enter your mobile or front desk number. Your agent puts callers through to it when they ask for a person. Without one, your agent takes a message instead.
2. If your opening hours are set as times, **Only during opening hours** is on: outside your hours your agent doesn't ring anyone. It takes a message, which appears in [Follow-ups](/follow-ups).
3. Press **Save changes**.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx -->

## How do I let my agent take bookings?

1. An **Admin** or **Developer** connects Google Calendar or Calendly on [Integrations](/integrations). For Calendly, choose which event callers book.
2. AI booking is on once a calendar is connected. The **Owner** or an **Admin** can switch **Let the agent book** on or off per calendar on [Bookings](/bookings), and set **Booking rules** for Google Calendar.

Every booking your agent makes then shows on [Bookings](/bookings), day by day.
<!-- source: ui/src/app/bookings/page.tsx, ui/src/app/integrations/page.tsx, api/services/tool_integrations/service.py -->

## Getting around: what's in the left menu?

On a computer, the left menu has:

- [Home](/overview): how your phone agent is doing.
- [Calls](/usage): every call your agent answered or made.
- [Follow-ups](/follow-ups): calls that need a person, with a count of open ones.
- [Bookings](/bookings): tables and appointments your agent booked.
- [Reports](/reports): your business in numbers.

Under **Your agent**:
- **What your agent knows**, **Phone number** and **Settings** (members, billing, notifications, privacy and more).

**Advanced setup** is a collapsed group for building agents: Voice agents, Models & voice, Telephony, Tools, Integrations, Files, Prompt audio and others. Most owners never need it.

You only see items your role allows.
<!-- source: ui/src/components/layout/navConfig.ts, ui/src/components/settings/settingsNav.ts -->

## Getting around on a phone

On a phone, the menu is a tab bar at the bottom of the screen: **Home**, **Calls**, **Follow-ups**, **Your agent** and **More**.

Tap **More** to open a sheet with everything else: your workspace name and role, the other screens such as Bookings and Reports, **Phone number** and **Settings** under **Your agent**, and **Advanced setup** ("Best on a computer"). At the bottom are **Help**, light or dark mode, and **Sign out**.
<!-- source: ui/src/components/layout/MobileTabBar.tsx -->

## How do I get help?

Press the **Help** button in the top bar. It has three parts:

- **Ask**: ask a question about LightMove in your own words.
- **Guides**: short how-to guides.
- **Contact support**: send a ticket to the LightMove team if you're stuck or something isn't working.

You can also use the contact form on the LightMove website: https://lightmove.ai/contact.
<!-- source: caller-provided description of the Help panel (not found in ui/src in this worktree) -->
