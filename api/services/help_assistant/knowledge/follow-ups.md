# Follow-ups
<!-- pages: /follow-ups -->

## What is the Follow-ups screen and what lands there?

**Follow-ups** lists "calls that need a person. Ring them back, then mark each one done." It covers calls from the last 30 days.

- **On a computer:** choose **Follow-ups** in the left menu. The number next to it is how many are still open.
- **On a phone:** tap **Follow-ups** in the bottom tab bar.

A call lands here when:

1. **Callback requested**: the caller asked to be called back, or left their details for a person.
2. **Transfer not answered**: your agent tried to pass the call to your team and nobody picked up.
3. **Rang more than once**: someone rang two or more times in a row and never reached anyone.
4. **Add an answer**: the call review found a question your agent couldn't answer.
5. **Time was full**: the caller wanted a time that was full (unless a booking was made anyway).

Open it here: [Follow-ups](/follow-ups).
<!-- source: ui/src/app/follow-ups/page.tsx, api/services/dashboard/follow_ups.py, ui/src/components/dashboard/dashboardView.ts, ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx -->

## How do I find a follow-up?

The **Follow-ups** screen has three tabs, each with a count:

- **To do**: still waiting. The caller who has waited longest comes first.
- **Done**: ones marked done in the last 30 days, with who sorted them.
- **All**: both.

Under the tabs:

1. Search with **Search names, numbers or what was said**.
2. Use the date chip (**Last 30 days** at first) to pick **Today** or **Last 7 days**, or choose days and press **Show these days**. Follow-ups only go back 30 days.
3. Use the kind chips (**Every kind**, **Call back**, **Transfer not answered**, **Rang more than once**, **Couldn't answer**, **Time was full**) to show one kind.

If a caller has several follow-ups, they are grouped under the caller's name. Press **Clear filters** if nothing matches.
<!-- source: ui/src/app/follow-ups/page.tsx, ui/src/app/follow-ups/FollowUpsFilters.tsx, ui/src/app/follow-ups/followUpsQuery.ts, ui/src/app/follow-ups/groups.ts, ui/src/components/dashboard/dashboardView.ts -->

## How do I call someone back from Follow-ups?

Each item on the **Follow-ups** screen shows who rang, what they wanted, when, and how long they have been waiting (for example "Waiting 2 h 30 min"). If they asked to be rung on a different number, it says "Asked to be rung on …".

- **On a phone**, press **Call back** to open your dialler.
- **On a computer**, the number is shown with a copy button, so you can ring it from your phone.
- Press **Listen** to hear the call first, when there is a recording.
- For **Time was full**, press **Open call** to see the call.

After you've spoken to them, press **Mark done**.
<!-- source: ui/src/components/dashboard/FollowUpRow.tsx, ui/src/components/dashboard/dashboardView.ts -->

## How do I mark a follow-up done, or undo it?

On the **Follow-ups** screen, press **Mark done** on the item. It moves to the **Done** tab and shows "Done" with who marked it and when.

Marked it by mistake? Open the **Done** (or **All**) tab and press **Undo** on the item. It goes back to **To do**.

Everyone on the team can do this: **Owner**, **Admin**, **Developer** and **Staff**. Whoever rings the caller back marks it done.

On **Home**, the **Needs your attention** card can also mark "couldn't answer" and "time was full" items done. Callbacks, unanswered transfers and repeat callers are marked done here on Follow-ups.

If the same person rings again later and still reaches nobody, a new follow-up opens.
<!-- source: ui/src/components/dashboard/FollowUpRow.tsx, ui/src/app/follow-ups/page.tsx, ui/src/components/dashboard/HomeDashboard.tsx, api/services/auth/permissions.py, api/services/dashboard/follow_ups.py -->

## How do I add an answer to a question my agent couldn't answer?

On the **Follow-ups** screen, items marked **Add an answer** show the question the caller asked.

1. Press **Add answer**.
2. Read **The caller asked**, then type **Your answer** (up to 500 characters).
3. Press **Save answer**.

The answer is added to your agent's answers to common questions, and the follow-up is marked done. You'll see "Answer added. Your agent uses it from its next call."

The **Owner**, an **Admin** or a **Developer** can add answers. **Staff** can still press **Mark done**.

If your agent's answers are full, shorten some on [What your agent knows](/workflow/{agent}/facts) and try again. You can also add answers from **Home** and **Reports**.
<!-- source: ui/src/components/dashboard/AddAnswerDialog.tsx, ui/src/app/follow-ups/page.tsx, ui/src/components/dashboard/FollowUpRow.tsx, api/services/auth/permissions.py -->

## What does the "This week" panel on Follow-ups mean?

Beside the list on the **Follow-ups** screen, the **This week** panel shows:

- **Follow-ups raised**: how many came in.
- **Sorted**: how many were marked done.
- **Usual wait before it's sorted**: the typical time between the call and someone marking it done (shown once there is enough to count).

These are "counted from your calls in the last 7 days, whatever the filters", so searching or picking a kind does not change them.

When everything is sorted, the list says **All caught up**: "Nobody is waiting on you."
<!-- source: ui/src/app/follow-ups/page.tsx -->
