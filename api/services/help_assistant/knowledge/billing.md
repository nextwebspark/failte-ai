# Billing
<!-- pages: /billing -->

## Where do I see my balance and billing?

Billing is on **Settings** > **Billing**. Open **Settings** in the left menu and choose **Billing**, or go to [Billing](/billing).

At the top you'll see three cards:
- **Credit balance**: your prepaid credit, excluding VAT.
- **Call rate**: what you pay per minute.
- **Plan**: for example **Self-serve** ("Pay as you go, no monthly fee").

Below that is **Billing history**: "Every top-up, call charge and credit, newest first."

The **Admin**, **Developer** and **Owner** roles can see Billing. **Staff** can't. Only an **Admin** can add credit or open invoices.
<!-- source: ui/src/app/billing/StripeBilling.tsx, ui/src/components/settings/settingsNav.ts, api/routes/billing.py, api/services/auth/permissions.py -->

## How much do calls cost?

On [Billing](/billing), the **Call rate** card shows your price. The standard rate is **€0.12 per minute**, excluding VAT.

Calls are "Billed per second of call time. Unanswered calls are free." There is no monthly fee on the **Self-serve** plan.

Each call's charge appears in **Billing history** on the Billing screen, with the amount and your balance after it. Enterprise accounts can have a different, agreed rate, which is what the Call rate card then shows.
<!-- source: api/services/billing/pricing.py, ui/src/app/billing/StripeBilling.tsx, api/routes/billing.py -->

## Do I get free credit when I sign up?

Yes. A new workspace starts with **€5 of free credit**, so you can try your agent before paying anything.

It appears on [Billing](/billing) under **Billing history** as **Welcome credit**, and is added once per workspace. At €0.12 a minute, that's enough for around 40 minutes of calls. When it runs low, an **Admin** can top up from €20 on the Billing screen.
<!-- source: api/services/billing/pricing.py, api/services/billing/accounts.py, ui/src/app/billing/StripeBilling.tsx -->

## How do I top up my credit?

Only an **Admin** can add credit.

1. Go to [Billing](/billing).
2. In **Add credit**, press one of the amounts: **€20**, **€50**, **€100** or **€250**.
3. Or type your own amount in "Other amount (min €20)" and press **Buy credit**.
4. You go to Stripe to pay securely.

The smallest top-up is **€20** and the largest is €5,000. VAT is added at checkout, and a VAT invoice is emailed for every payment. EU businesses can enter their VAT number for reverse charge.

When you come back you'll see "Payment received. Your credit will appear in a moment." If you cancel, "You have not been charged."
<!-- source: api/services/billing/pricing.py, api/services/billing/checkout.py, ui/src/app/billing/StripeBilling.tsx -->

## Where are my invoices and receipts?

A VAT invoice is emailed for every payment.

To see them all, an **Admin** can open [Billing](/billing) and press **Invoices & receipts** at the top of the screen. This opens your invoices in Stripe.

The **Billing history** table on the Billing screen also lists every top-up, call charge and credit, with the **Date**, **Activity**, **Amount** and **Balance** after each one.
<!-- source: ui/src/app/billing/StripeBilling.tsx, api/routes/billing.py -->

## What happens when my credit runs low or runs out?

**Low credit:** Admins are emailed when spendable credit drops below €5, and again when it's too low to start a call.

**Out of credit:** a new call can only start when you have at least €0.50 of credit. Below that, the **Credit balance** card on [Billing](/billing) says "Calls are paused until you top up." Your agent won't take calls until an **Admin** adds credit.

**During a call:** when a call starts, its length is capped at what your balance can pay for (never less than one minute), so a call can end if credit runs out.

To avoid this, top up on [Billing](/billing) before you run low.
<!-- source: api/services/billing/pricing.py, api/services/billing/notifications.py, api/services/quota_service.py, api/services/billing/guard.py, ui/src/app/billing/StripeBilling.tsx -->

## What is the Done-for-you plan?

On [Billing](/billing) you'll see plan cards: **Self-serve**, **Done-for-you** and **Enterprise**. Your current one is marked **Current**.

- **Self-serve**: build your own agents, pay per minute, no monthly fee.
- **Done-for-you**: "We design and build your agent for a one-time €550, including €50 of call credit. Then pay as you go." An **Admin** on Self-serve can press **Get it built for you** to pay by Stripe.
- **Enterprise**: custom terms, invoiced monthly. Use **Contact sales** where shown, or https://lightmove.ai/contact.
<!-- source: ui/src/app/billing/StripeBilling.tsx, api/services/billing/pricing.py -->
