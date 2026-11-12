# Pass calls to your team
<!-- pages: /workflow/{agent}/facts, /follow-ups -->

## How do I let my agent put callers through to a person?

Your agent can ring a phone of your choice when a caller asks for a person. Set it up on **What your agent knows**, in the **What your agent can do** card, under **Pass calls to your team**.

1. Open [What your agent knows](/workflow/{agent}/facts).
2. In **Pass calls to your team**, type your mobile or front desk number.
3. Press **Save changes**.

The row then shows "On" and says it puts callers through to that number when they ask for a person. If you leave the number empty, it shows "Off" and your agent takes a message instead.

The **Owner**, an **Admin** or a **Developer** can change this. **Staff** can only see it. You'll only see this row if your agent was made from a ready-made agent that can pass calls on.
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, api/services/auth/permissions.py, api/routes/workflow.py -->

## How is my transfer number checked?

On **What your agent knows**, under **Pass calls to your team**, LightMove checks the number as you type. Type it the way you'd normally write it, for example 087 123 4567. A number without a country code is read as Irish.

When it's fine you'll see how it will be saved, for example "✓ Irish mobile · saved as +353 87 123 4567". When it can't be used you'll see why, for example:

- "That number is too short. Check the digits…"
- "That number has too many digits. Check it and try again."
- "That isn't a number that can be called. Check the digits."
- "Premium-rate numbers can't be used. Use a mobile or landline."
- "We don't recognise that country code. Start with + and the country code…"

Saving runs the same check, so a number that fails can't be saved.
<!-- source: ui/src/lib/transferNumber.ts, ui/src/app/workflow/[workflowId]/facts/TransferOptions.tsx, api/utils/transfer_number.py, api/routes/workflow.py -->

## Can I pass calls to an extension on my phone system?

Yes. On **What your agent knows**, under **Pass calls to your team**, you can enter an address on your own phone system (a SIP address) instead of a phone number. The check then shows "✓ Phone system address · dialled as typed", and LightMove dials it exactly as you typed it.

For a normal mobile, landline or direct line, just type the number, and LightMove saves it in full international form.
<!-- source: api/utils/transfer_number.py, ui/src/lib/transferNumber.ts -->

## Why is my own business number refused for transfers?

On **What your agent knows**, **Pass calls to your team** refuses your agent's own phone number with this message: "This is the number callers ring. If it forwards to your agent, transfers go round in a circle. Use a different phone, such as a mobile or a direct line."

This prevents a loop. If you forward your business number to your agent, and your agent then passes calls back to that same number, the call just comes back to the agent.

LightMove can only refuse the agent's own numbers. If you forward your main line or your mobile to the agent (see the [Phone number](/workflow/{agent}/deployment) screen), don't enter that forwarded number here either. Use a different phone, such as a colleague's mobile or a direct line that isn't forwarded.
<!-- source: api/utils/transfer_number.py, api/routes/workflow.py, docs/customer-guides/phone-and-transfer-setup.md -->

## How do I stop transfers when we're closed?

On **What your agent knows**, under **Pass calls to your team**, there's a switch called **Only during opening hours**. It only appears once your opening hours are set as times. Until then the screen says "Set your opening hours as times (under Your business) to pass calls only while you're open."

- **On** (the default once hours are set as times): "Outside your hours, your agent doesn't ring anyone. It takes a message, which appears in Follow-ups."
- **Off**: "Your agent tries to put callers through at any hour." This suits emergency call-outs.

After changing the switch, press **Save changes**. If your hours are written as text rather than times, your agent always tries to put callers through. Messages appear in [Follow-ups](/follow-ups).
<!-- source: ui/src/app/workflow/[workflowId]/facts/page.tsx, ui/src/app/workflow/[workflowId]/facts/openingHours.ts, api/services/workflow/opening_hours.py -->

## Can my phone show the caller's number when a call is passed to me?

On **What your agent knows**, under **Pass calls to your team**, once a number is entered there's a switch: **Show the caller's number when we pass a call to you**. It's on unless you switch it off. Changes apply from the next call.

What your phone actually shows depends on your agent's phone provider, and the screen tells you which applies:

- "Your phone shows the caller's number. If your phone provider refuses it, it shows your agent's number instead." This is for numbers from Twilio or Telnyx, including LightMove numbers.
- "Your phone shows your agent's number. Your phone provider doesn't let us show the caller's." This is for other providers.

Before your agent has a phone number, it says: "Where your phone provider allows it…". The **Owner**, an **Admin** or a **Developer** can change the switch.
<!-- source: ui/src/app/workflow/[workflowId]/facts/TransferOptions.tsx, ui/src/lib/transferNumber.ts, api/routes/workflow.py, api/utils/transfer_number.py, api/services/telephony/platform_numbers/twilio.py -->

## What happens on a call when my agent passes it on?

When a caller asks for a person and **Pass calls to your team** has a number on **What your agent knows**:

1. Your agent says "One moment, I'm putting you through." and the caller hears hold music while your phone rings.
2. If you answer, you're talking to the caller. On some phone providers you first hear "You have answered a transfer call. Connecting you now."
3. If nobody answers in about 30 seconds, your agent comes back to the caller and the call shows as "Transfer not answered".

A test call with **Try your agent** in the browser can't put you through, because transfers only work on real phone calls. To test a transfer, ring your agent's number from a phone.
<!-- source: api/routes/workflow.py, api/services/workflow/pipecat_engine_custom_tools.py, api/services/telephony/providers/twilio/provider.py, api/services/telephony/providers/plivo/routes.py, docs/customer-guides/phone-and-transfer-setup.md -->

## What does "Transfer not answered" mean?

"Transfer not answered" means your agent tried to pass a call to your team, but nobody picked up. You'll see it as a call result on [Calls](/usage) and [Home](/overview), and as a follow-up in [Follow-ups](/follow-ups). The follow-up shows what the caller wanted, or "Your agent tried to pass the call to your team, but nobody picked up." If the same person rang several times, it also says how many times they rang without reaching anyone.

Ring the caller back, then mark the follow-up done. To make it less likely:

- Check the number in **Pass calls to your team** on [What your agent knows](/workflow/{agent}/facts).
- Make sure that phone isn't forwarded back to your agent.
- Check its voicemail settings (see the voicemail tip).
<!-- source: ui/src/components/dashboard/dashboardView.ts, api/services/dashboard/calls.py, ui/src/components/dashboard/FollowUpRow.tsx -->

## Voicemail tip for transfers

When your agent passes a call to your team (set under **Pass calls to your team** on **What your agent knows**), it waits about 30 seconds for someone to answer. If your phone's voicemail picks up before then, the caller may end up in your voicemail instead of your agent taking a message.

To avoid this, on the phone you use for transfers:

- set voicemail to answer after more than 30 seconds, or
- turn voicemail off.

Then ring your business number from another phone and ask for a person to check it works.
<!-- source: docs/customer-guides/phone-and-transfer-setup.md, api/services/workflow/pipecat_engine_custom_tools.py -->
