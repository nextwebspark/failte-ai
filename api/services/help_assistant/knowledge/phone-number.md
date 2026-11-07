# Phone number
<!-- pages: /workflow/{agent}/deployment, /telephony-configurations -->

## Where do I set up my agent's phone number?

The **Phone number** screen is where you choose how callers reach your agent.

- **On a computer:** in the left menu, under **Your agent**, choose **Phone number**. With one agent it opens that agent's phone setup.
- **On a phone:** tap **More** in the bottom tab bar, then **Phone number** under **Your agent**.

The screen asks "How should callers reach (your agent)?" and says "You can change this later." Below it there is also a **Website** section with **Set up the website widget**, for a call button on your website.

Open it here: [Phone number](/workflow/{agent}/deployment).
<!-- source: ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx, ui/src/app/workflow/[workflowId]/deployment/page.tsx, ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx -->

## Who can set up the phone number?

Phone setup on the **Phone number** screen is for an **Admin** or a **Developer**. They can get a number, connect a phone provider account and press the check button.

If you're the **Owner** or **Staff**, the screen shows "Ask a workspace admin to set up a phone number for this agent." Ask an Admin in your workspace to do it.

The Owner can still change everything on [What your agent knows](/workflow/{agent}/facts), including the number calls are passed to.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx, api/routes/phone_setup.py, api/services/auth/permissions.py, ui/src/lib/auth/roles.ts -->

## Which option should I choose: keep my number, a new number, or my mobile?

On the **Phone number** screen, pick one of three ways in:

- **Keep my existing number** (marked "Most common"): callers ring the number they already know. You forward it to your agent.
- **Get a new number**: a new local number just for your agent. LightMove provides it, or you use your own phone provider account. Put it on your website, Google listing and cards.
- **My mobile is my business number**: forward your mobile to the agent when you're busy or don't answer.

Whichever you choose, your agent needs a number of its own. Forwarded calls go there. You don't need to share it with anyone.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/phoneForwarding.ts, ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx -->

## How do I get a LightMove number?

On the **Phone number** screen, if your agent has no number yet, step 1 **Your agent's number** offers **LightMove provides the number**. No phone company account is needed.

1. Choose **Local number** or **Mobile number** to see what's available.
2. Pick a number from the list.
3. Press **Get this number**. It rings your agent straight away.

If there are none of that kind, you'll see "No numbers of this kind right now. Try the other kind, or ask us."

If the box says **Coming soon**, LightMove numbers aren't ready yet. Use the **Ask us** link and the team will set one up for your agent, or use your own phone provider account instead.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx, api/routes/phone_setup.py -->

## How do I forward my existing number or mobile to my agent?

On the **Phone number** screen, choose **Keep my existing number** or **My mobile is my business number**. Then:

1. Copy your agent's number in step 1, **Your agent's number**.
2. Under **When should calls go to your agent?**, pick:
   - **When we don't answer**: your phone rings first, and after about 20 seconds your agent picks up.
   - **When we're busy**: only when the line is engaged.
   - **All calls**: your agent answers every call.
   - **Outside opening hours**: set a timed forward with your phone company. Not every provider offers it.
3. Under **Turn on forwarding**, the screen shows the code to dial on most mobiles, with your agent's number filled in. Press **Copy**, dial it and press call.

On a landline or office phone system, ask your phone company (eir, Vodafone, Virgin Media, BT…) to forward to your agent's number.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/phoneForwarding.ts, ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx -->

## What are the mobile forwarding codes?

The **Phone number** screen shows the exact code with your agent's number already in it. These are the standard codes most mobiles accept:

- **When we don't answer:** `**61*` + agent number + `**20#`
- **When we're busy:** `**67*` + agent number + `#`
- **All calls:** `**21*` + agent number + `#`
- **Outside opening hours:** there's no code. Ask your phone company.

To undo forwarding, dial `##002#`. This cancels all forwarding on most mobiles.

Not every network or phone accepts these codes. If yours doesn't, ask your mobile network to forward calls to your agent's number. For a landline, ask your phone company.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/phoneForwarding.ts, ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx -->

## How do I check that forwarding works?

The last step on the **Phone number** screen is **Check it works**. LightMove never makes a test call itself. It waits for a real call to reach your agent.

1. Press **I've set it up – check now**.
2. Ring your own number from another phone. If you chose **Get a new number**, ring your agent's number from your own phone.
3. When your agent answers, the step turns green: "It works. Your agent answered its first call…". Where your phone company passes it on, it also shows "Forwarded from your number".

If no call has arrived yet, you'll see "No call yet. We'll keep looking while this page is open." The page checks again by itself while it stays open.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx, api/routes/phone_setup.py -->

## Why does it say my number is an extension?

On the **Phone number** screen, your agent's number may be an extension on your own phone system (for example a short number like 7000) rather than a full phone number. Calls made inside that phone system to the extension reach your agent.

A mobile or landline can only forward to a full phone number. So for **Keep my existing number** or **My mobile is my business number**, the screen warns "Phones can't forward to an extension" and shows no forwarding code.

To forward your number, your agent needs a full number: choose **Get a new number**, or add a number from your phone provider. If you already dialled a forwarding code for the extension, cancel it with `##002#`.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx, ui/src/app/workflow/[workflowId]/deployment/phoneForwarding.ts -->

## Can I use my own Twilio or other phone provider account?

Yes. On the **Phone number** screen, open **Advanced: use my own phone provider account** (it's called **Manage this agent's numbers** once your agent has a number). This is for numbers from a phone provider account you connect yourself, like Twilio or Telnyx.

- If your workspace has no phone accounts yet, press **Set up phone numbers** to connect the provider once on the [Telephony](/telephony-configurations) screen, add a number, then come back.
- If you already have numbers, press **Connect a phone number**, pick one and press **Connect**. If another agent answered that number, it stops.
- **Add a new number** goes to your provider's page to add one.
- **Disconnect** stops a number ringing this agent.

Only an **Admin** or a **Developer** can do this.
<!-- source: ui/src/app/workflow/[workflowId]/deployment/PhoneSetup.tsx, ui/src/app/workflow/[workflowId]/deployment/AgentPhoneNumbers.tsx -->

## What is the Telephony screen?

The [Telephony](/telephony-configurations) screen lists "The phone accounts and numbers your agents answer and call from." Find it in the left menu under **Advanced setup** › **Telephony**. Only an **Admin** or a **Developer** can open it.

To connect a provider, press **Add provider**, give it a **Name**, choose the **Provider** and fill in the account details the form asks for. The **Provider** list shows the providers available to your workspace, such as Twilio, Telnyx, Plivo or Vonage. Phone numbers are added after the account is created: open the account and add the number.

Most business owners don't need this screen. A LightMove number, if offered on the **Phone number** screen, needs no provider account.
<!-- source: ui/src/app/telephony-configurations/page.tsx, ui/src/components/telephony/ConfigFormDialog.tsx, ui/src/components/telephony/PhoneNumberDialog.tsx, ui/src/components/layout/navConfig.ts, api/services/telephony/providers -->
