# Calls
<!-- pages: /usage -->

## Where do I see all my calls?

The **Calls** screen lists every call your agent answered, with the recording and what was said. Everyone on your team can open it.

- **On a computer:** choose **Calls** in the left menu.
- **On a phone:** tap **Calls** in the bottom tab bar.

Above the list are four tabs, each with its count:

- **All**: every call.
- **Needs follow-up**: calls with an open follow-up, the same ones as the Follow-ups screen (always the last 30 days).
- **Bookings**: calls where a booking was made, moved, requested or cancelled.
- **Passed to team**: calls your agent put through to a person.

The list shows 10 calls per page. By default it shows the **Last 7 days**.

Open it here: [Calls](/usage).
<!-- source: ui/src/app/usage/page.tsx, ui/src/app/usage/callsView.ts, ui/src/app/usage/CallsFilters.tsx, ui/src/components/layout/navConfig.ts, ui/src/components/layout/MobileTabBar.tsx, api/services/auth/permissions.py -->

## How do I search my calls, including what was said?

On the **Calls** screen, type in the box that says **Search names, numbers or what was said**. It searches:

- the caller's name, as your agent took it down;
- the phone number;
- the call's summary;
- anything said on the call, by the caller or your agent.

The list updates as you type (or press Enter). Press the **X** in the box to clear it.

When you open a call from a search, the matching words are marked in **What was said**, with a line such as "“parking” is marked in 2 lines". If the words only matched the caller or the summary, it tells you so.

The search keeps your tab and date choice, so check the date chip if a call is missing.
<!-- source: ui/src/app/usage/CallsFilters.tsx, ui/src/app/usage/callsView.ts, ui/src/app/usage/CallPanel.tsx, api/db/filters.py -->

## How do I filter calls by date or by who handled them?

Next to the search box on the **Calls** screen:

1. **Date chip** (shows **Last 7 days** at first): pick **Today**, **Last 7 days**, **Last 30 days**, **Last 90 days** or **Any time**. Or pick days on the calendar and press **Show these days**. On the **Needs follow-up** tab the dates are fixed to "Last 30 days, as on Follow-ups".
2. **Who handled it**: choose **Anyone**, **Your agent** or **Passed to your team**.
3. **More filters**: opens **Find calls**, with extra filters such as **Call ID** and **Agent**. Choose a filter under **Choose what to filter by**, then press **Apply**. This also opens **Time zone for call times**, where you can change the time zone used for call times.

If nothing matches you'll see **No calls match**. Press **Clear filters** to go back to every call.
<!-- source: ui/src/app/usage/CallsFilters.tsx, ui/src/app/usage/callsView.ts, ui/src/app/usage/page.tsx, ui/src/components/filters/FilterBuilder.tsx -->

## What do I see when I open a call?

On the **Calls** screen, press a call to open it. On a computer it opens beside the list (the newest call shows there by itself). On a phone it fills the screen; press **Back to calls** to return.

The call shows:

- the outcome, the time and the length, then the caller's name and number, and how many times they "called before";
- **Summary**: a short written summary of the call;
- **What they wanted**: the reason for the call;
- the recording;
- **Your agent couldn't answer**: questions it didn't know, with a link to **Add the answer in What your agent knows**;
- **What was said**: the conversation;
- **Details your agent took**, such as name, number to call back, date, time or party size.

**Technical details** shows the agent, Call ID and kind of call, plus **Open full page** (the step-by-step record, for whoever set up your agent).
<!-- source: ui/src/app/usage/CallPanel.tsx, ui/src/app/usage/page.tsx, ui/src/app/usage/callsView.ts -->

## How do I listen to or download a call recording?

On the **Calls** screen:

1. Press the play button on a call in the list. The call opens and the recording starts.
2. Or open the call and use the player under **What they wanted**.
3. To keep a copy, press **Download recording** near the bottom of the call.

If there is no player, the call tells you why:

- "This call is still going on." The recording appears when it ends.
- "The recording isn't ready yet. It usually appears a minute or two after the call ends." Press **Check again**.
- "No recording was kept for this call."
- "We couldn't load the recording." Press **Try again**.

You can also listen from **Home** (the play button in **Recent calls**) and from **Follow-ups** (**Listen**).
<!-- source: ui/src/app/usage/CallPanel.tsx, ui/src/app/usage/CallsTable.tsx, ui/src/components/dashboard/HomeDashboard.tsx, ui/src/components/dashboard/FollowUpRow.tsx -->

## How do I read the transcript of a call?

Open the call on the **Calls** screen and look under **What was said**. Each line is marked **Agent** or **Caller**.

- The first few lines show at first. Press **Show the whole conversation** to see it all, and **Show less** to fold it again.
- If you searched for words, they are marked in the lines where they appear, and the whole conversation opens if a match is further down.
- While a call is still going on, it says "What was said shows here once the call ends."
- For some calls the text is offered as a file instead: press **Open the written transcript**.

If nothing was said, it shows "Nothing was said on this call."
<!-- source: ui/src/app/usage/CallPanel.tsx -->

## How do I share a call recording with someone?

You can make a link that lets anyone listen to one recording without signing in. Anyone on your team who can see calls can do this.

1. Open the call on the [Calls](/usage) screen.
2. Press **Share recording**.
3. Under **The link works for**, pick **7 days** or **24 hours**.
4. Press **Make a link**, then **Copy link**.

Copy it straight away: "for safety we don't keep a copy of the link". If you lose it, press **Make another link**.

The person who opens it sees your business name, the date and length of the call, a player, and when the link expires. They never see the caller's number or name. The page asks them not to pass the link on.

**Share recording** only appears on calls that have a recording.
<!-- source: ui/src/app/usage/ShareRecordingDialog.tsx, ui/src/app/listen/[token]/SharedRecording.tsx, api/routes/recording_shares.py -->

## How do I stop a shared recording link from working?

On the **Calls** screen, open the call and press **Share recording**. Under **Links that work now** you see each live link, when it works until, and who made it.

Press **Revoke** next to a link. You'll see "Link turned off. It stops working straight away."

If the list says "None. Nobody outside your team can listen to this call.", there are no working links.

When someone opens a link that no longer works, they see one of:

- **This link has expired**: links only work for 24 hours or 7 days.
- **This link was turned off**: someone revoked it.
- **This recording is no longer available**: the recording isn't kept any more.

They are told to ask whoever sent it for a new link.
<!-- source: ui/src/app/usage/ShareRecordingDialog.tsx, ui/src/app/listen/[token]/SharedRecording.tsx, api/routes/recording_shares.py -->

## Where does the call summary come from?

After each finished phone call that comes in, LightMove writes a short review of the call automatically. It is shown on the **Calls** screen when you open a call:

- **Summary**: one or two lines on what happened, for example a booking made and a question asked.
- **What they wanted**: the reason for the call.
- **Your agent couldn't answer**: questions your agent didn't know.

The review can also notice when a caller wanted a time that was full. These findings create items on the Follow-ups screen, and the reasons feed **What callers wanted** on Home and Reports.

Browser test calls, text chats and calls your agent makes out are not reviewed, so they have no summary. Calls where the caller said nothing are marked "Hung up without speaking."
<!-- source: api/services/call_review/__init__.py, api/services/call_review/review.py, api/services/call_review/service.py, api/services/dashboard/follow_ups.py, ui/src/app/usage/CallPanel.tsx -->

## How do I call a caller back from the Calls screen?

Open the call on the **Calls** screen and press **Call back** near the bottom.

- **On a phone**, it opens your dialler with the number.
- **On a computer**, it shows "Ring them back on" with the number and a **Copy number** button.

It uses the number the caller asked to be rung on if your agent took one down, otherwise the number they rang from. There is no **Call back** button on test calls, or when there is no number that can be rung (for example a withheld number and no call-back number taken).

If something looks wrong with a call, press **Report a problem** to email support about that call.

To keep track of who still needs ringing, use [Follow-ups](/follow-ups).
<!-- source: ui/src/app/usage/CallPanel.tsx -->

## How do I download a list of my calls?

On the **Calls** screen, press **Download list** at the top right. You get a spreadsheet file (calls.csv) of every call the list is showing, across all pages. It follows the tab, search, date and filters you have chosen.

While it is being made the button says **Preparing…**. If it fails you'll see "We couldn't make the list. Please try again."

The [Reports](/reports) screen also has a **Download** button for the calls in the report's period.
<!-- source: ui/src/app/usage/page.tsx, ui/src/app/reports/page.tsx -->

## A caller asked for a copy of their calls or to delete them. What do I do?

On the **Calls** screen, press **More filters**. An **Admin** sees a box called **A caller wants their data**: "If someone asks for a copy of their calls, or for them to be deleted, start here." Press **Caller data request** to start.

Only an Admin sees this. If you are the Owner or Staff, ask an Admin on your team. Other privacy settings are under [Privacy & compliance](/settings/compliance).
<!-- source: ui/src/app/usage/page.tsx, ui/src/components/privacy/CallerDataRequestDialog.tsx, ui/src/components/settings/settingsNav.ts, api/services/auth/permissions.py -->
