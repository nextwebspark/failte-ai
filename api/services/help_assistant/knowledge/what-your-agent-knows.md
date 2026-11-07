# What your agent knows
<!-- pages: /workflow/{agent}/facts -->

## Where do I find "What your agent knows"?

**What your agent knows** is the screen where you keep your business details, answers and opening hours up to date. Your agent uses them from its next call.

- **On a computer:** in the left menu, under **Your agent**, choose **What your agent knows**. If you have one agent, it opens straight away. If you have several, pick the agent from the list first.
- **On a phone:** tap **Your agent** in the bottom tab bar.

The page has a **Your business** card, **Answers to common questions**, **What your agent can do**, **How it sounds** and **Ready to take calls**.

Open it here: [What your agent knows](/workflow/{agent}/facts).
<!-- source: ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx, ui/src/app/workflow/[workflowId]/facts/page.tsx -->

## Who can change what my agent knows?

On **What your agent knows**, the **Owner**, an **Admin** or a **Developer** can change business details, opening hours, answers and the "Pass calls to your team" settings.

**Staff** members can see the page but not change it. Instead of the save buttons they see "Only the owner or an admin can change these."

Changing the agent's voice, opening **See all voices**, and asking for a custom voice are only for an **Admin** or a **Developer**. If you are the Owner and want a different voice, ask an Admin. You can manage who has which role on the [Team](/team) screen if you are allowed to manage members.
<!-- source: api/services/auth/permissions.py, ui/src/lib/auth/roles.ts, ui/src/app/workflow/[workflowId]/facts/page.tsx, api/routes/workflow.py -->

## How do I change my business details and save them?

1. Open [What your agent knows](/workflow/{agent}/facts).
2. In the **Your business** card, edit the details your agent gives callers, such as your address, opening hours and **Website or menu link**. Fields marked "Optional" can be left empty.
3. A counter shows how many unsaved changes you have, for example "2 unsaved changes".
4. Press **Save changes**. You'll see "Saved. Your agent uses these from its next call."

Press **Discard** to undo changes you haven't saved yet.

If a required answer is empty, saving stops with "Fill in the required answers before saving." and the field shows "Your agent needs this answer. Please fill it in."

Saving here doesn't need you to publish the agent.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, api/routes/workflow.py -->

## How do I set my opening hours as times?

On **What your agent knows**, the **Opening hours** row in **Your business** can be plain text or set times. Set times let your agent know when you're open, and stop it passing calls to your team while you're closed.

1. Press **Set your hours as times**. It starts as Monday to Friday, 9 to 5.
2. Press a day to change it. Use the **Open on (day)** switch, then pick **Opens** and **Closes** times.
3. For a lunch break, press **Add opening time** to add a second time slot that day. You can have up to 4 per day.
4. **Same hours on every open day** copies that day's hours to the other open days.
5. Check **Time zone**, and add a note under **Anything to add?** (for example "Closed on bank holidays").
6. Press **Save changes**.

Under "Your agent says:" you can read the sentence callers will hear. A closing time earlier than the opening time means the next day. To go back to text, press **Write your hours out instead**.
<!-- source: ui/src/app/workflow/[workflowId]/facts/OpeningHoursEditor.tsx, ui/src/app/workflow/[workflowId]/facts/openingHours.ts -->

## Why won't my opening hours save?

On **What your agent knows**, set opening hours are checked before saving. The message tells you what to fix:

- "(Day): the opening times overlap or are out of order." Put that day's time slots in order, and make sure they don't overlap.
- "(Day): only the last opening time can run past midnight." Only the day's last time slot can close after midnight.
- "(Day): at most 4 opening times." Remove a time slot.
- "The note is too long (at most 200 characters)." Shorten the **Anything to add?** note.

Fix it, then press **Save changes** again.
<!-- source: ui/src/app/workflow/[workflowId]/facts/openingHours.ts, ui/src/app/workflow/[workflowId]/facts/page.tsx -->

## How do I add answers to common questions?

On **What your agent knows**, the **Answers to common questions** card has a box called **Anything else callers often ask?** Write answers there in plain words, for example about parking, prices, payment options or the languages you speak. Your agent reads them out when callers ask.

1. Open [What your agent knows](/workflow/{agent}/facts).
2. Type or edit your answers in the box.
3. Press **Save changes**.

Your agent uses the new answers from its next call. The box has a size limit. If it's full, shorten some answers before adding more.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/components/dashboard/AddAnswerDialog.tsx -->

## How do I answer a question my agent couldn't answer?

When a caller asks something your agent couldn't answer, the question shows in a blue box on **What your agent knows**, above your answers. It says "No answer yet. Add one so your agent can help next time." It also appears in [Follow-ups](/follow-ups) as "Add an answer".

1. Press **Add answer** next to the question.
2. In the **Add an answer** box, read "The caller asked", then type under **Your answer**.
3. Press **Save answer**.

Your answer is saved straight away and added to **Answers to common questions**. The follow-up is marked done. You'll see "Answer added. Your agent uses it from its next call."

Only the **Owner**, an **Admin** or a **Developer** see **Add answer**.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/components/dashboard/AddAnswerDialog.tsx, ui/src/components/dashboard/FollowUpRow.tsx, ui/src/components/dashboard/dashboardView.ts, ui/src/app/follow-ups/page.tsx -->

## What does "What your agent can do" show?

The **What your agent can do** card on **What your agent knows** only lists things your agent really does:

- **Take bookings**: shown when your agent books into Google Calendar or Calendly. It says whether the calendar is "Connected". The Owner, an Admin, or a Staff member the Owner allowed can switch booking on or off here. If the calendar isn't connected, an Admin or Developer sees a **Reconnect** link to [Integrations](/integrations). Change booking times on [Bookings](/bookings).
- **Pass calls to your team**: the number your agent puts callers through to when they ask for a person, and whether to do it only during opening hours.

If neither applies to your agent, the card isn't shown.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/app/workflow/[workflowId]/facts/knowledge.ts, api/services/auth/permissions.py -->

## How do I hear and change my agent's voice?

On **What your agent knows**, the **How it sounds** card shows your agent's voice next to a few others.

1. Press the play button on a voice to hear it read your greeting (or a short sample sentence if you have no spoken greeting). Nothing plays until you press play.
2. To switch, press the voice's name, then **Use (name)**. Or press **Cancel**.

You'll see that test calls use the new voice straight away. Phone calls switch when the agent is next published.

For the full list, press **See all voices** (or **Change the voice**) to open the agent's [Model and voice](/workflow/{agent}/model) screen under Advanced setup.

Only an **Admin** or a **Developer** can switch voices. Everyone can press play.
<!-- source: ui/src/app/workflow/[workflowId]/facts/VoiceChips.tsx, ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/app/workflow/[workflowId]/facts/voiceOptions.ts, ui/src/components/layout/agentNav.ts -->

## Can I use my own voice or a cloned voice?

On **What your agent knows**, under **How it sounds**, the **Your own voice** box is marked "Coming soon". Soon you'll be able to record your own voice there.

If you already have a cloned voice with **ElevenLabs** or **Cartesia** (or another provider), you can ask the LightMove team to set it up:

1. Press **I already have a cloned voice**.
2. Under **Where is it?**, choose **ElevenLabs**, **Cartesia** or **Another provider**.
3. Enter the **Voice ID**. It's shown next to the voice in your provider's voice list. Optionally add a **Voice name** and a note under **Anything else?**
4. Tick the box to confirm it's your own voice, or that you have the speaker's written permission.
5. Press **Send request**.

The team sets it up by hand and gets in touch. Your agent will still tell callers it's an AI. Only an **Admin** or a **Developer** can send a request.
<!-- source: ui/src/app/workflow/[workflowId]/facts/CustomVoice.tsx, api/routes/custom_voice.py, api/services/custom_voice/__init__.py -->

## Do I send my ElevenLabs or Cartesia password or API key?

No. Never send a password or an API key with a custom voice request. The **Use a voice you already have** form on **What your agent knows** only asks for the provider and the **Voice ID**. The team will tell you how to share the voice with LightMove.

If you paste something that looks like an API key into **Voice ID**, the request is refused with "That looks like an API key, not a voice ID. Please don't send keys."

After you send it, the **Your own voice** box shows the date you asked, for example "You asked us on (date) to set up your voice. We'll be in touch to finish it." Press **Send another request** to send a new one.
<!-- source: ui/src/app/workflow/[workflowId]/facts/CustomVoice.tsx, api/services/custom_voice/__init__.py -->

## What does "Ready to take calls" mean?

The **Ready to take calls** card on **What your agent knows** is a short checklist:

- **Business details added**, or a reminder to add the required details that are still missing.
- **Calendar connected**, "Calendar not connected" or "Choose your Calendly event", if your agent takes bookings.
- **Phone number linked**, or "No phone number linked yet". Set the number up on the [Phone number](/workflow/{agent}/deployment) screen.

Admins and Developers also see **Open advanced setup**, for changing how calls flow step by step.

To hear your agent before callers do, press **Try your agent** in the **How it sounds** card. It opens a test call in your browser.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx -->

## Why does it say "This agent has no business details to edit here"?

Agents made from a ready-made agent template keep their opening hours, address and answers on **What your agent knows**. If an agent was built another way (for example started from scratch), its wording lives in the conversation itself. The page then shows "This agent has no business details to edit here." with a link to the conversation.

The conversation is under **Advanced setup** and is usually changed by an Admin or Developer. To get an agent that uses this page, create one from a ready-made agent on [New voice agent](/workflow/create).
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/components/workflow/CreateAgentWizard.tsx -->
