# LightMove.ai UI v3 — design audit and redesign plan

This folder is the design source of truth for the v3 UI pass. Read this file
before changing the app shell, the Voice agents screens, the agent editor, or
any token in `ui/src/app/globals.css`.

- **Live canvas (private, owner can share):** https://claude.ai/artifact/4wGuWvjM7DChzCZSLbcpJ7
- **Local copy:** the `*.dc.html` files here are the same boards. Each one is a
  self-contained HTML page that renders with the `support.js` next to it.
- **Brand source:** `brand-kit/lightmove-brand/BRAND.md` and `tokens.css`. This
  plan follows the kit; where the app departs from it, the kit wins.
- **Older canvas:** `../Failte AI v2.dc.html` is the v2 design the current shell
  was built from. v3 keeps its layout (header, nav panel, content panel, test
  rail) and changes the look and the screens listed below.

## Boards

| File | What it shows |
| --- | --- |
| `Main.dc.html` | The audit: 15 findings graded high / medium / low, with the file each comes from, the design principles, and the order of work. |
| `System.dc.html` | Foundations side by side in light and dark: surfaces, ink, accents, type scale, buttons, inputs, pills, nav rows, radius, elevation. |
| `Agents.dc.html` / `AgentsDark.dc.html` | The Voice agents landing: stat strip, search and status filter, folder groups, the new row model. |
| `CreateAgent.dc.html` | The single Create agent dialog: Describe it, Start from a template, Blank canvas. |
| `Conversation.dc.html` / `ConversationDark.dc.html` | The agent editor: one editor toolbar, floating canvas toolbar, node styling, test rail with live state. |
| `Settings.dc.html` / `SettingsDark.dc.html` | Advanced settings: section index, setting rows, one sticky save bar. |

The `*Dark` boards import their light twin with `dark` set, so a change to the
light board is a change to both.

## Design principles

1. **One accent.** Brand green (`--brand`) does every interactive job: primary
   buttons, active nav, focus rings, selection, links. Sky, amber, red and
   orange are status tones, never buttons.
2. **Spark orange means live.** `--live` is only for a call happening now: the
   live pill, the node the call is on, the speaking waveform.
3. **Same opening on every screen.** Title, one-line description, actions on
   the right, then content. Nothing repeated in the app header.
4. **Flat surfaces, floating overlays.** Cards have no shadow or texture.
   Shadows only on menus, popovers, dialogs and floating toolbars.
5. **Rows, not button rows.** A list row navigates; secondary actions live in
   one kebab menu.
6. **Dark uses the Uncava ladder.** Cool near-black page, two surface steps,
   white-alpha hairlines, cool grey text, all lifted from
   `nextwebspark/app-lightmove` (`claude-design/uncava-tokens.css`). Mint stays
   the only accent; Uncava's indigo is not used. Light mode uses Uncava's
   light surfaces and a true near-black ink. Status tones stay the
   contrast-tuned LightMove values in both themes. The theme follows the OS until the user picks one.
7. **"Agent" is the only word users see.** Never "workflow" in UI copy (code
   identifiers keep their names). Sentence case for buttons and headings.

## Foundations (implemented in step 1)

| Token | Light | Dark |
| --- | --- | --- |
| `--bg` | `#f7f8fa` | `#08090b` |
| `--panel` | `#ffffff` | `#0e1013` |
| `--panel-2` | `#f7f8fa` | `#15181d` |
| `--line` | `rgba(3,7,18,.09)` | `rgba(255,255,255,.08)` |
| `--ink` / `--ink-2` / `--ink-3` | `#0b0d12` / `#3a414d` / `#596170` | `#f4f6f8` / `#a6adbb` / `#7c8493` |
| `--brand` | `#0e7a4b` | `#3ddc97` |
| `--ring`, `--sidebar-primary` | `--brand` | `--brand` |

- **Type:** DM Sans for interface (400 body, 500 interface, 600 headings, 700
  screen titles). Sora 600 for the wordmark and display numbers. JetBrains Mono
  for data only: ids, timers, numbers, keys.
- **Radius:** 6 chips (`rounded-sm`), 8 controls (`rounded-md`), 12 cards and
  dialogs (`rounded-lg`), 14 shell panels (`rounded-xl`). No `rounded-[Npx]`.
- **Buttons:** 32 toolbar and table, 36 default, 40 form CTA.

## Plan

Status is kept here so the next session knows where to pick up.

| Step | Scope | Status |
| --- | --- | --- |
| 1 | **Foundations.** DM Sans, Uncava dark tokens, near-black light ink, green ring and active nav, radius scale, flat Card, system-aware theme, Stack Auth theme in step. Files: `ui/src/app/globals.css`, `ui/src/app/layout.tsx`, `ui/src/components/ui/*`, `ui/src/components/layout/*`, `ui/src/components/ThemeSwitcher.tsx`, `ui/src/app/handler/[...stack]/stack-theme.ts`. | Done |
| 2 | **Copy pass.** "Agent" everywhere in customer-facing UI strings, default name "Untitled agent", sentence case on the agent list, create flow, editor, tester, settings, runs, reports and telephony screens. The internal superadmin pages and the CSV export column names were left as they are. | Done |
| 3 | **Voice agents landing.** Stat strip (agents, calls in the last 24 h with change, calls in 7 days, last call), search, filter (All / Draft edits), sort (last call, name, newest), first-agent empty state. Rows: initial circle, name with id and created date, StatusPill ("Published", plus a "Draft edits" chip when saved edits are not published yet: a draft never takes an agent offline), calls with a 7-day sparkline, last call, one ⋯ menu (Open, Move to folder, Archive / Restore). Folders start open; a search or filter shows one flat list of matches. The list endpoint now returns `runs_7d`, `last_run_at` and `has_draft` per agent. Files: `ui/src/components/workflow/AgentList.tsx`, `WorkflowTable.tsx`, `ui/src/lib/agentList.ts`, `api/db/workflow_client.py` (`get_workflow_run_activity`, `get_workflow_ids_with_draft`), `api/routes/workflow.py`. | Done |
| 4 | **Create flow.** One Create agent dialog (`ui/src/components/workflow/CreateAgentDialog.tsx`, steps in `components/workflow/create/`), built for non-technical users around ready-made agents. It opens on "What should your agent do?": the templates as cards (featured first, filters when they both answer and make calls). Picking one asks its setup questions about the business, with a live preview of the greeting and, where the template books, a Connect Google Calendar button (sign-in runs in a pop-up so the answers stay; see `app/integrations/oauthPopup.ts`). It ends on "Your agent is ready" with Talk to your agent. "Describe it in your own words" and "Start from scratch" are the quieter links. Templates carry `setup_fields` (questions whose answers fill `{{key}}` placeholders), card details and `integrations`; starters live in `api/services/workflow/starter_templates.py` and are written with `python -m scripts.sync_agent_templates`. `/workflow/create` redirects to `/workflow?create=template`. Mockup: the "Create agent: template-first" design canvas. | Done |
| 5 | **Editor.** One toolbar in `WorkflowEditorHeader.tsx`: the agent's name is the rename control, then the version pill (opens history), Read only / Unsaved / error pills, and Phone call / Save / Publish / more on the right. Publish is always there and says why it is disabled (save first, fix the errors, nothing new to publish). It no longer portals into the app header. One bottom-centre floating canvas toolbar (`components/CanvasToolbar.tsx`): Add step, zoom out / zoom % / zoom in, fit, tidy, undo / redo; view controls only on an old version. The test rail header reads "Test agent" with a LIVE timer pill while a browser call is connected and a compact Voice / Text switch. On phones the editor's actions and the page actions in the top bar wrap instead of running off-screen. | Done |
| 6 | **Advanced settings.** `workflow/[workflowId]/settings/page.tsx`: a page title, a sticky section index (General, Call behaviour, Variables, Dictionary, Voicemail and screening, Identity, Recordings, Reporting) with an unsaved dot per section, shown when the page is wide enough. Cards with an icon header and label-left / control-right rows (`settings/SettingsLayout.tsx`, sized by the card with container queries). One sticky save bar (`settings/SettingsSaveBar.tsx`) replaces the per-card Save buttons: it names the sections with changes, says why saving is blocked, discards everything, and saves in one go. General and Voicemail now go out as one merged configurations save (each used to send a stale copy of the other's fields and the name), after the Variables and Dictionary saves. Variables became a name / default value table. | Done |
| Guardrail | `no-restricted-syntax` in `ui/eslint.config.mjs` fails any string with a raw Tailwind palette class (`text-red-500`, `bg-sky-50`, `border-amber-200`, …) and points to the tokens. The 57 files that used them were moved to tokens by role: text → `text-danger` / `text-amber` / `text-sky` / `text-ok`, pale fills → `bg-*-dim`, borders → `border-*/30`, greys → ink / line / panel, and their `dark:` twins dropped (the tokens switch themselves). Solid fills under white text use `text-brand-ink`, and status badges use the dim style. The onboarding tooltip is now a panel popover with a brand button instead of a blue box, and shares the dialogs' z-50 layer, so it shows over the test-rail sheet it points into while a dialog opened later covers it. The sign-in screens' always-dark brand panel (`components/auth`, `app/handler`) and tests are exempt. | Done |

## Known leftovers

- `.page-actions` in `globals.css` still sizes the buttons other screens send to
  the top bar (Voice agents, Campaigns, Tools, …). The editor no longer uses it.
- The agent nav's version status still uses its own inline pill rather than
  `StatusPill`.
- The Voice agents board shows a Channels column (phone, web widget) and Talk
  time / Live now stats. They need phone-number, embed and call-duration data on
  the list endpoint and were left out of step 3.
- The editor design's node restyle (coloured step icons, tool/skill chips) and
  the canvas legend were not part of step 5.
