# Voice agents
<!-- pages: /workflow, /workflow/create, /workflow/{agent}/home -->

## What is a voice agent?

A voice agent is the AI that answers phone calls for your business. It greets callers, answers questions using what you've told it, and can take bookings, take messages or pass calls to your team.

Most businesses have one agent. You manage it from the left menu under **Your agent**: [What your agent knows](/workflow/{agent}/facts) for its details and answers, and [Phone number](/workflow/{agent}/deployment) for how callers reach it.

To see all your agents, open **Advanced setup** in the left menu and choose **Voice agents**, or go to [Voice agents](/workflow). On a phone, tap **More**, then **Advanced setup**.
<!-- source: ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx, ui/src/components/workflow/AgentsEmptyState.tsx -->

## How do I create a new agent?

Go to [New voice agent](/workflow/create), or press **Create agent** on [Voice agents](/workflow). Only an **Admin** or a **Developer** can create agents.

1. **Choose template:** "What should your agent do?" Pick a ready-made agent, preview it, and press **Use this template**.
2. **Personalise:** fill in your business details (name, opening hours, address, website) and, if the agent takes bookings, connect a calendar (optional). Press **Create agent**.
3. **Ready:** "Your agent is ready". Press **Talk to your agent** to test it in your browser. Nobody else hears it until you give it a phone number. Use **Give it a phone number** when you're ready.

You can also choose **Describe it in your own words →** and press **Build my agent** (about 20 seconds), or **Start from scratch** for an empty agent you build yourself.
<!-- source: ui/src/components/workflow/CreateAgentWizard.tsx, ui/src/components/workflow/create/AgentReady.tsx, ui/src/components/workflow/create/TemplateGallery.tsx, ui/src/components/workflow/AgentsEmptyState.tsx, ui/src/components/layout/navConfig.ts -->

## What is the agent dashboard?

When you open an agent, you land on its [Dashboard](/workflow/{agent}/home). It's the same view as [Home](/overview), but it only shows this agent's calls, under the agent's name. From there you can press **Try your agent** to talk to it in your browser.

The agent's own menu also has **What your agent knows** and **Calls**, which lists every call this agent has taken.
<!-- source: ui/src/app/workflow/[workflowId]/home/page.tsx, ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/layout/agentNav.ts -->

## What is the conversation builder under Advanced setup?

Most owners never need it. Your business details, answers, opening hours and transfer number are all on [What your agent knows](/workflow/{agent}/facts).

For people who build agents, each agent has an **Advanced setup** group in its menu:

- **Conversation**: the steps a call follows. Changes here go live when you publish the agent.
- **Model and voice**: the voice and language this agent uses ([Model and voice](/workflow/{agent}/model)).
- **Advanced settings**: behaviour, variables, dictionary and diagnostics ([Advanced settings](/workflow/{agent}/settings)).
- **Deployment**: put this agent on a phone number or your website.

On a phone, **Advanced setup** is marked "Best on a computer".
<!-- source: ui/src/components/layout/agentNav.ts, ui/src/components/layout/MobileTabBar.tsx, ui/src/app/workflow/[workflowId]/components/WorkflowEditorHeader.tsx, ui/src/app/workflow/[workflowId]/facts/page.tsx -->
