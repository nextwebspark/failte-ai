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
| 3 | **Voice agents landing.** New row model (initial circle, name and meta, StatusPill, channels, runs with 7-day sparkline, last call, kebab menu), search, status filter, stat strip, empty state. Needs per-agent `runs_7d` and `last_call_at` on the workflow list endpoint in `api/`. | To do |
| 4 | **Create flow.** One dialog replaces the dropdown and the `/workflow/create` page; generation shown inside the dialog; land in the editor with the test rail open. | To do |
| 5 | **Editor.** One toolbar in `WorkflowEditorHeader.tsx` (name as rename control, version pill, unsaved and error pills, Phone call / Save / Publish / more); stop portalling into the app header. One bottom-centre floating canvas toolbar in `RenderWorkflow.tsx`. Test rail header with live pill and Voice / Text control in `WorkflowTesterPanel.tsx`. | To do |
| 6 | **Advanced settings.** Sticky section index, label-left / control-right rows, one sticky save bar driven by `UnsavedChangesContext`, replacing the seven per-card Save buttons in `workflow/[workflowId]/settings/page.tsx`. | To do |
| Guardrail | Lint rule banning raw Tailwind palette classes (`text-red-500`, `bg-sky-50`, …), then migrate the ~54 files it flags to tokens. | To do |

## Known leftovers after step 1

- `.page-actions` in `globals.css` still forces header buttons to toolbar size.
  It goes away when step 5 moves the editor actions out of the header.
- Raw palette classes remain in about 54 files (for example the run detail page
  uses `bg-sky-50` / `text-sky-700`). The guardrail step handles them.
- The agent nav's version status still uses its own inline pill rather than
  `StatusPill`.
