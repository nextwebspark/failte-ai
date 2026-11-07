# Business facts: what the agent knows, editable by the owner

An agent made from a starter template keeps its business details on the
agent, not baked into its prompts. The owner can then update them at any
time, with no agent editor.

## How it works
- **Creation.** The setup wizard's business questions are marked `stored`
  (business name, description, opening hours, address, website, "anything
  else callers ask"). `fill_template` (`api/services/workflow/template_setup.py`)
  does two things with them:
  - it saves the answers as the agent's template context variables;
  - it rewrites each prompt placeholder to
    `{{initial_context.<key> | fallback:…}}`.

  Other answers (e.g. the booking-question toggles) are still written into
  the prompts.
- **Every call reads the current facts.** Inbound phone calls (carrier
  webhooks and Asterisk) now load the agent's stored variables, as test and
  outbound calls already did. Values the call itself sets (caller number,
  etc.) take precedence.
- **Editing.** The agent's **Business facts** tab (`/workflow/<id>/facts`)
  lists the facts its prompts use and saves through
  `PUT /api/v1/workflow/{id}/business-facts`. The save updates the agent, its
  live version and any draft together, so it applies from the next call
  without publishing a developer's unfinished changes. Clearing an optional
  fact brings back the prompt's fallback (e.g. "not listed").

## Putting callers through to a person
Every inbound template asks for an optional **"Number to put callers
through to a person"**. It's a stored fact like the others, so it can be set
or changed later on Business facts.

- **Creation.** One transfer tool is created for the agent. Its destination
  is `{{initial_context.transfer_number}}`, and every conversation step can
  use it (placeholder `builtin:transfer-call`, swapped in
  `attach_tool_placeholder`).
- **Instructions.** The agent's global prompt says to transfer only when a
  number is set, never to read the number out, and to take a message if
  the transfer doesn't connect (or no number is set).
- **Carriers.** Transfers work on Asterisk/ARI, Twilio, Telnyx, Plivo and
  Cloudonix, but not on Vonage, Vobiz or Exotel; there the tool fails and
  the agent takes a message.

## Opening hours as times
The owner can set the opening hours as times on "What your agent knows":
per weekday closed or one or more ranges (12:00–15:00 and 17:00–22:00), a
range past midnight (18:00–02:00), the time zone (default Europe/Dublin)
and an optional note ("Closed on bank holidays").

- **Storage.** No new table: the times are a fact like the others,
  `opening_hours_schedule`, holding `OpeningHours`
  (`api/schemas/opening_hours.py`) as JSON text. Saving also writes the
  `opening_hours` sentence the prompts read, generated from the times
  ("Tuesday to Sunday 12 to 3 pm and 5 to 10 pm, closed Monday"), and the
  `timezone` fact. Through `PUT /business-facts` with
  `opening_hours_schedule` (null removes the times and keeps the sentence).
- **Free text stays.** An agent with only free-text hours keeps them until
  the owner sets times; nothing is parsed from the text. While times are
  set, the text can't be edited on its own.
- **Transfers.** With times set and "Only during opening hours" on (the
  default), the transfer tool rings nobody while the business is closed in
  its zone. It returns `status: transfer_failed`, `reason: closed`, and the
  agent offers to take a message. Without times, transfers are tried as
  before (`opening_hours.transfer_closed`).
- **Home and reports** count calls that came in outside the hours, for
  agents that have times; the others are named as not counted.
- **Wizard.** The create-agent setup still asks for the hours as text; the
  owner sets times afterwards.

## Who can edit
`agents:facts`: Owner, Developer and Admin. Owners still can't open the
agent editor (`agents:write`). Anyone who can see the agent can read the
facts.

## Limits
- Agents built before this change, or by the AI builder, have their wording
  inside the prompts. Their Business facts tab says so and has nothing to
  edit.
- Changing the booking-question toggles after creation still needs the
  agent editor.
