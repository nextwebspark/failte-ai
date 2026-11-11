# Team and roles
<!-- pages: /team, /account -->

## Where do I manage my team?

Your team is managed on **Settings** > **Members**. Open it from **Settings** in the left menu, or go to [Members](/team).

**Members** lists everyone with access to this workspace, their **Role** and when they **Joined**. Your own row is marked **You**. Admins also see **Pending invitations**.

**Admin**, **Developer** and **Owner** can open Members. **Staff** members don't see it. Only an **Admin** can invite people, change roles or remove members.
<!-- source: ui/src/app/team/page.tsx, ui/src/app/team/MembersCard.tsx, ui/src/components/settings/settingsNav.ts, api/services/auth/permissions.py -->

## What roles are there and what can each do?

On [Members](/team) every person has one of four roles:

- **Admin**: "Everything, including members, billing and workspace settings." Only Admins can invite, remove members, top up credit, change workspace settings and delete the workspace.
- **Developer**: "Builds and configures agents, telephony, integrations and API keys." Developers can't switch AI booking or manage who gets emailed after calls.
- **Owner**: "The business owner: sees everything, runs bookings and decides which staff can too." The Owner also keeps "What your agent knows" up to date, chooses notifications and email reports, and can view billing.
- **Staff**: "View-only: calls, bookings and reports. The owner can let them manage bookings." Staff can also mark follow-ups done.

The person who creates a workspace starts as its Admin.
<!-- source: ui/src/lib/auth/roles.ts, api/services/auth/permissions.py, api/services/auth/depends.py -->

## How do I invite a team member?

Only an **Admin** can invite.

1. Go to [Members](/team).
2. Press **Invite member**.
3. Enter their **Email** and pick a **Role**. Each role shows a short description. The role is "Developer" until you change it.
4. Press **Send invitation**.

They get an email with a link to join. The link works once and expires in 7 days.

If the email couldn't be sent, you'll see "The invitation email could not be sent. Share this link with them directly", with a link you can copy and send yourself.
<!-- source: ui/src/app/team/InviteDialog.tsx, ui/src/app/team/InviteLinkNotice.tsx, api/services/invitations/service.py -->

## How do I resend or cancel an invitation?

Admins see **Pending invitations** on [Members](/team): invitations that haven't been accepted yet, with the email, role and when each expires.

- To send it again, press the resend (circular arrow) button. If the email still can't be sent, a link to share by hand appears.
- To cancel it, press the revoke (X) button. You'll see "Invitation to … revoked".

If you send a lot of invitations in a short time you may see "Too many invitations sent recently; try again later".
<!-- source: ui/src/app/team/InvitationsCard.tsx, api/errors/invitations.py -->

## How do I change someone's role?

Only an **Admin** can change roles.

1. Go to [Members](/team).
2. In the person's **Role** column, open the role picker and choose the new role.

You'll see a message like "Sam is now a staff". If you change your own role, the app reloads so your new permissions take effect.

A workspace must always keep at least one Admin, so you can't move the only Admin to another role. Make someone else an Admin first.
<!-- source: ui/src/app/team/MembersCard.tsx, ui/src/app/team/RoleSelect.tsx, api/errors/membership.py -->

## How do I let a staff member manage bookings?

**Staff** can only view bookings to begin with. The **Owner** or an **Admin** can let a staff member switch AI booking on and off.

1. Go to [Members](/team).
2. Find the staff member. Under their role, turn on **Can manage bookings**.

You'll see "… can now switch AI booking on and off". Turn it off and they "can now only view bookings".

The switch only shows for Staff. Owners and Admins already manage bookings, and Developers can't. Turning it on lets the person use the switches on [Bookings](/bookings).
<!-- source: ui/src/app/team/MembersCard.tsx, api/routes/team.py, api/services/auth/permissions.py -->

## How do I remove a member, or leave a workspace?

**Remove someone** (Admins only):
1. Go to [Members](/team).
2. Press the bin icon on their row and confirm **Remove**.

They lose access immediately and their API keys in this workspace are deactivated. You can't remove the only Admin.

**Leave yourself**: on your own row (marked **You**), press the leave icon and confirm **Leave**. You'll lose access until someone invites you again. To delete your whole account instead, see [Your account](/account).
<!-- source: ui/src/app/team/MembersCard.tsx, api/routes/team.py, api/errors/membership.py -->

## Where can I see my own role?

Your role is shown on **Settings** > [Your account](/account), under **Profile**, next to **Role**. It says "Set by an admin on Members." Your email and the workspace you're in are shown there too.

On a phone, your workspace name and role are also shown at the top of the **More** sheet.

If you need a different role, ask an Admin to change it on [Members](/team).
<!-- source: ui/src/app/account/page.tsx, ui/src/components/layout/MobileTabBar.tsx -->
