# Try your agent
<!-- pages: /workflow/{agent}/home, /workflow/{agent}/facts, /workflow/{agent}/deployment, /workflow/{agent}/settings, /workflow/{agent}/model, /overview -->

## How do I test my agent in the browser?

You can talk to your agent from your computer before (or after) callers do. The **Test agent** panel sits on your agent's screens.

1. Open one of your agent's screens, for example [What your agent knows](/workflow/{agent}/facts) or [your agent's home](/workflow/{agent}/home).
2. Open the panel:
   - On a wide computer screen it is pinned on the right.
   - On smaller screens, press **Test agent** at the top of the page (on phones it is a robot icon). The panel slides in.
   - On **What your agent knows** the panel starts closed: press **Try your agent**.
3. You can also press **Try your agent** on [Home](/overview). It opens your agent's home with the panel open.

The panel stays open, with your test, while you move between your agent's screens.
<!-- source: ui/src/components/layout/AgentTestRail.tsx, ui/src/components/layout/AppTopBar.tsx, ui/src/components/layout/shellContext.ts, ui/src/context/AgentShellContext.tsx, ui/src/components/workflow/agentLinks.ts, ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/app/workflow/[workflowId]/home/page.tsx, ui/src/components/dashboard/HomeDashboard.tsx -->

## How do I make a test call with my voice?

In the **Test agent** panel, stay on the **Voice** tab. It says **Talk to your agent**: "Have a conversation through your computer's microphone, just like a caller would."

1. Press **Start a test call**. Nobody else is called.
2. If your browser asks to use the microphone, allow it.
3. Talk as a customer would. A **Live** pill shows how long the call has run, and the conversation appears in the panel.
4. Press **End Call** when you're done.
5. Press **Start Another Test** to try again. If the call couldn't connect, press **Retry Call**.

Switching to the **Text** tab ends a voice test.
<!-- source: ui/src/app/workflow/[workflowId]/components/WorkflowTesterPanel.tsx, ui/src/app/workflow/[workflowId]/components/workflow-tester/EmbeddedVoiceTester.tsx -->

## Can I test my agent by typing instead of talking?

Yes. In the **Test agent** panel, choose the **Text** tab, then **Manual**. It says **Chat with this agent**: send messages and see how your agent responds.

- Type a message as a caller would and send it.
- Press **Reset** to start a fresh chat.

The **Simulated** option, where an AI plays the caller, shows **Coming soon** and can't be used yet.

Like a voice test, a text chat can't put the caller through to a person.
<!-- source: ui/src/app/workflow/[workflowId]/components/WorkflowTesterPanel.tsx, ui/src/app/workflow/[workflowId]/components/workflow-tester/shared.tsx, ui/src/app/workflow/[workflowId]/components/workflow-tester/AiSimulatorPlaceholder.tsx, api/services/workflow/pipecat_engine_custom_tools.py -->

## Why can't my browser test transfer the call to my team?

Browser tests can't transfer calls. The **Test agent** panel says: "Putting a caller through to a person only works on a real phone call."

If you ask for a person during a browser test, your agent tells you: "I'm sorry, but call transfers are not available for web calls. Please try a telephony call." In a text chat it says call transfers "are not available in text chat tests".

To test passing calls to your team:

1. Find your agent's number on [Phone number](/workflow/{agent}/deployment) (in the left menu under **Your agent**).
2. Make sure someone can answer the number your agent passes calls to.
3. Ring your agent's number from your mobile and ask for a person.

The real call then shows on [Calls](/usage), marked **Passed to your team** or **Transfer not answered**.
<!-- source: ui/src/app/workflow/[workflowId]/components/WorkflowTesterPanel.tsx, api/services/workflow/pipecat_engine_custom_tools.py, ui/src/components/layout/navConfig.ts, ui/src/components/dashboard/dashboardView.ts -->

## Who can run a browser test of the agent?

Starting a voice test or a text chat in the **Test agent** panel needs the **Admin** or **Developer** role. For other roles the test is refused with "Your role does not allow this action".

If you are the **Owner** or **Staff** and can't start a test, ask an Admin, or ring your agent's real phone number from your mobile instead. That is a real call, so it is counted on Home and gets a summary on Calls.
<!-- source: api/routes/workflow.py, api/routes/workflow_text_chat.py, api/services/auth/depends.py, api/services/auth/permissions.py, ui/src/lib/auth/roles.ts -->

## Where do my test calls show up?

Browser test calls and text chats appear on the [Calls](/usage) screen. With no caller name they are listed as **Test call** or **Test chat**. Open one and look under **Technical details**: the kind says "Call from the browser (test)" or "Text chat (test)".

Test calls:

- don't count on [Home](/overview): "Test calls don't count on this page";
- don't get a written **Summary** or **What they wanted**, because only real incoming phone calls are reviewed;
- have no **Call back** button.
<!-- source: ui/src/app/usage/CallsTable.tsx, ui/src/app/usage/CallPanel.tsx, ui/src/components/dashboard/HomeDashboard.tsx, api/services/call_review/service.py -->

## Why does the Test agent panel say "Testing is paused"?

The **Test agent** panel shows **Testing is paused** with a reason when a test can't start. For example, while you're editing your agent's conversation in **Advanced setup**:

- "Save the latest draft before testing so the session uses the version you are looking at."
- "Resolve the current validation errors before starting another test."

Save or fix the change, then press **Start a test call** again.
<!-- source: ui/src/app/workflow/[workflowId]/components/workflow-tester/shared.tsx, ui/src/app/workflow/[workflowId]/RenderWorkflow.tsx, ui/src/app/workflow/[workflowId]/components/WorkflowTesterPanel.tsx -->
