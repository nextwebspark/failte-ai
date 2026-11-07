# Integrations
<!-- pages: /integrations, /bookings -->

## What are Integrations for?

The **Integrations** screen is where you connect the apps you already use, like **Google Calendar** or **Calendly**, so your agent can check free times and book callers while they are still on the line.

Find it in the left menu under **Advanced setup** > **Integrations**, or go straight to [Integrations](/integrations).

The screen has two parts:
- **Your connections**: the apps already connected, each with a status such as "Connected", "Needs attention" or "Setup incomplete".
- **Available integrations**: the apps you can connect, each with a **Connect** button (or **Add another** if one is already connected).

Once a calendar is connected, its bookings show on [Bookings](/bookings).
<!-- source: ui/src/app/integrations/page.tsx, ui/src/app/integrations/ConnectionCard.tsx, ui/src/app/integrations/ProviderCard.tsx, ui/src/components/layout/navConfig.ts -->

## Who can connect or remove an integration?

On the **Integrations** screen, only an **Admin** or a **Developer** can connect, test or remove a connection. Anyone else who opens it sees "You can view integrations. Ask a workspace admin or developer to connect or remove them."

The **Owner** and **Staff** roles don't see the Integrations screen at all. If you are the Owner and want a calendar connected, ask an Admin on your team. You can still turn AI booking on or off yourself on [Bookings](/bookings) once the calendar is connected.

Roles are managed on [Members](/team).
<!-- source: api/routes/integrations.py, api/services/auth/permissions.py, ui/src/app/integrations/page.tsx, ui/src/app/bookings/page.tsx -->

## How do I connect Google Calendar?

You need to be an **Admin** or **Developer**.

1. Open [Integrations](/integrations).
2. Under **Available integrations**, find Google Calendar and press **Connect**.
3. If your LightMove setup offers it, you'll see "Sign in with your Google account. No setup needed." Press **Connect with Google** and sign in with Google.
4. Google sends you back to Integrations and you see "Connected as" your account name.

If you are asked for a **Client ID** and **Client secret** instead, signing in with Google hasn't been set up for your workspace by the platform. You can follow the on-screen steps to use your own Google Cloud OAuth client, or contact support.

Finish in the same browser tab you started from, within 10 minutes, or the sign-in can't be confirmed.
<!-- source: ui/src/app/integrations/OAuthConnect.tsx, ui/src/app/integrations/ConnectDialog.tsx, ui/src/app/integrations/page.tsx -->

## How do I connect Calendly?

You need to be an **Admin** or **Developer**.

1. Open [Integrations](/integrations) and press **Connect** on Calendly.
2. Choose how to connect. You can sign in with your Calendly account, or use a **Personal access token**: in Calendly open your profile menu, then **Developer**, then **Personal access tokens**, create a token, and paste it in. LightMove checks it with Calendly before saving it.
3. Next, pick the event callers book in "Which Calendly event should callers book?". You can change it later with **Change event**.

Good to know:
- Until an event is chosen, your agent takes the caller's details instead.
- Calendly needs the caller's email address to book; your agent asks for it and spells it back.
- Your agent can't move or cancel Calendly bookings.
- Working hours, notice and limits come from Calendly.
<!-- source: ui/src/app/integrations/TokenConnect.tsx, ui/src/app/integrations/ChoiceDialog.tsx, ui/src/app/integrations/CalendlyNotes.tsx, ui/src/app/integrations/ConnectionCard.tsx -->

## How do I turn AI booking on or off for a calendar?

AI booking is switched per calendar on the [Bookings](/bookings) screen, under **Your calendar**.

1. Open [Bookings](/bookings).
2. On the calendar's card, use the **Let the agent book** switch. The badge shows "Agent books" or "Booking off".

When booking is off, your agent won't book on that calendar. Callers who want a booking are passed to your team, or their details are taken for a call back.

For Google Calendar there's also **Let the agent cancel or move bookings**. The agent only does this after the caller gives the phone number the booking was made under, plus their name or the day of the booking.

Who can switch these: the **Owner**, an **Admin**, and **Staff** members the Owner or an Admin has allowed. **Developers** cannot.
<!-- source: ui/src/app/bookings/page.tsx, api/routes/integrations.py, api/services/auth/permissions.py -->

## How do I let a staff member manage bookings?

By default, **Staff** members can only view bookings. The **Owner** or an **Admin** can let a staff member switch AI booking on and off.

1. Go to Settings > [Members](/team).
2. Find the staff member. Under their role, turn on **Can manage bookings**.

You'll see "(name) can now switch AI booking on and off". Turn it off again and they "can now only view bookings".

This switch only appears for Staff. Owners and Admins already manage bookings.
<!-- source: ui/src/app/team/MembersCard.tsx, api/routes/team.py, api/services/auth/permissions.py -->

## What does "Needs attention" mean, and how do I fix it?

On [Integrations](/integrations), a connection marked **Needs attention** means LightMove couldn't use it, for example because access was withdrawn. On [Bookings](/bookings) you may see "Couldn't read this calendar", and your agent can't offer times from it until it's fixed.

An **Admin** or **Developer** can:
- Press **Test** to check the connection.
- Press **Reconnect** and sign in again. Once the new connection works, you're offered "Remove the old connection?".

If a sign-in finished but wasn't confirmed, the card says "Awaiting confirmation". Press **Finish setup** in the same browser you signed in with, or remove it and connect again.
<!-- source: ui/src/app/integrations/ConnectionCard.tsx, ui/src/app/integrations/page.tsx, ui/src/app/bookings/page.tsx -->

## How do I disconnect a calendar?

You need to be an **Admin** or **Developer**.

1. Open [Integrations](/integrations).
2. On the connection under **Your connections**, press **Remove**.
3. Confirm "Remove this … connection?".

Agents using it lose access straight away, so your agent can no longer offer times from that calendar. You can connect again at any time.
<!-- source: ui/src/app/integrations/ConnectionCard.tsx, ui/src/app/integrations/page.tsx, api/routes/integrations.py -->

## Why does Integrations say "Integrations aren't switched on yet"?

If the [Integrations](/integrations) screen shows "Integrations aren't switched on yet", connecting apps isn't set up for this LightMove deployment. Nothing in your workspace can fix it. Ask your administrator, or contact support through the **Help** button or https://lightmove.ai/contact.

You may also see "Signing in with an account isn't set up on this server yet." when you try to connect. That means account sign-in for that app hasn't been set up on the platform.
<!-- source: ui/src/app/integrations/page.tsx, ui/src/app/integrations/OAuthConnect.tsx -->
