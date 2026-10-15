# LightMove.ai — Brand Guide (for Claude Code)

LightMove.ai is an AI voice agent platform for Irish businesses and VoIP operators.
This folder is the single source of truth for the visual brand. When restyling the app,
use ONLY the values defined here and in `tokens.css` / `tokens.json`.

## Instructions for Claude Code

1. Copy `tokens.css` into the app's global styles and import it once at the root (e.g. `app/globals.css` in Next.js).
2. Copy `logo/*.svg` into `public/brand/`. Use `favicon.svg` as the site favicon.
3. Load fonts: Sora (600), DM Sans (400/500/600), JetBrains Mono (400/500). In Next.js use `next/font/google`.
4. Replace every hard-coded colour, font family, radius and shadow in the app with the CSS variables from `tokens.css`. Do not introduce new colours.
5. Support light and dark mode: light is the default; dark applies via `prefers-color-scheme: dark` OR `[data-theme="dark"]` on `<html>`. Both are already defined in `tokens.css`.
6. If the app uses Tailwind, map the theme colours/fonts/radii to these CSS variables (see "Tailwind mapping" below) instead of using Tailwind's default palette.
7. Logo in the header: render `mark.svg` (32px) followed by the wordmark as live text: `LightMove` in Sora 600, letter-spacing −0.03em, colour `--lm-text`, then `.ai` in `--lm-brand-text`.
8. Work screen by screen, keep all existing functionality, and check contrast rules below.

## Logo

- Mark: green rounded square (radius = 25% of size) with four white voice-wave bars and a small orange "spark" dot above the last bar.
- Files:
  - `logo/mark.svg` — full colour, default everywhere
  - `logo/mark-reversed.svg` — white tile, green bars; for green backgrounds
  - `logo/mark-mono-ink.svg` — single colour, dark
  - `logo/mark-mono-white.svg` — single colour, light (photos, video)
  - `logo/favicon.svg` — simplified, no spark (for 32px and below)
  - `logo/logo-light.svg` / `logo/logo-dark.svg` — mark + wordmark (text uses Sora; in the app, prefer mark + live text as in step 7)
- Clear space: half the mark's height on all sides.
- Minimum size: mark 24px; full logo 120px wide.
- Don't: recolour the mark, stretch it, add shadows/gradients, or put the full-colour mark on busy photos.

## Colour

| Token | Light | Dark | Use |
|---|---|---|---|
| `--lm-green` | #169B62 | #169B62 | Logo, icons, large fills (Irish Green) |
| `--lm-brand-text` | #0E7A4B | #3DDC97 | Links, brand-coloured text |
| `--lm-primary` | #0E7A4B | #3DDC97 | Primary button fill |
| `--lm-on-primary` | #FFFFFF | #0A1F17 | Text on primary button |
| `--lm-spark` | #FF883E | #FF883E | Live-call dot, logo spark only |
| `--lm-bg` | #F7FAF8 | #0A1F17 | Page background |
| `--lm-surface` | #FFFFFF | #133227 | Cards, panels, inputs |
| `--lm-border` | #DCE7E1 | #24493B | Borders, dividers |
| `--lm-text` | #0B1F17 | #F2F7F4 | Headings, body |
| `--lm-text-muted` | #4A5A52 | #9DB5A9 | Secondary text |
| `--lm-success-bg` / `--lm-success-text` | #E8F5EE / #0E7A4B | #133227 / #3DDC97 | "Answered" badge |
| `--lm-warning-bg` / `--lm-warning-text` | #FFF0E6 / #A84A0C | #3A2414 / #FFB27F | "Needs follow-up" badge |
| `--lm-neutral-bg` / `--lm-neutral-text` | #EEF2F0 / #4A5A52 | #1B3A2F / #9DB5A9 | "Voicemail" badge |

Contrast rules:
- White text on Irish Green #169B62 only at 24px+ (3.6:1). For buttons use `--lm-primary` (#0E7A4B, 5.4:1).
- Spark orange is never used for text or large areas.

## Typography

| Role | Font | Size / line height | Weight |
|---|---|---|---|
| H1 | Sora | 56 / 60 | 600, tracking −0.03em |
| H2 | Sora | 40 / 44 | 600, tracking −0.02em |
| H3 | Sora | 28 / 34 | 600, tracking −0.01em |
| H4 | DM Sans | 20 / 28 | 600 |
| Body | DM Sans | 16 / 26 | 400 |
| Small | DM Sans | 14 / 20 | 400 |
| Label | DM Sans | 12 / 16 | 600, uppercase, tracking 0.08em |
| Data | JetBrains Mono | 14 / 20 | 400 — timers, phone numbers, logs, keys |

On mobile, scale H1 to 36/40 and H2 to 28/34.

## Shape & spacing

- Radius: 8px (small), 12px (buttons, inputs), 16px (cards), 24px (large panels), 999px (pills/badges).
- Spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 56, 64.
- Buttons and touch targets: minimum height 44px.
- Shadow: only `--lm-shadow` (soft) on raised cards in light mode; none in dark mode.
- Icons: outline/stroke style, 1.75px stroke, rounded caps (e.g. Lucide). No emoji in the UI.

## Components (reference)

- Primary button: bg `--lm-primary`, text `--lm-on-primary`, radius 12, height 44, DM Sans 15/600.
- Secondary button: transparent bg, 1.5px border `--lm-primary`, text `--lm-brand-text`.
- Ghost button: no border, text `--lm-text`.
- Badge: pill, 13px/600, padding 6×12, using the success/warning/neutral token pairs.
- Live-call indicator: 8px `--lm-spark` dot + label "LIVE CALL" in Label style, colour `--lm-brand-text`.
- Waveform: rounded vertical bars in `--lm-brand-text`; inactive bars in `--lm-border`.

## Tailwind mapping

Tailwind v4 (in the global CSS, after importing `tokens.css`):

```css
@theme inline {
  --color-bg: var(--lm-bg);
  --color-surface: var(--lm-surface);
  --color-border: var(--lm-border);
  --color-fg: var(--lm-text);
  --color-muted: var(--lm-text-muted);
  --color-brand: var(--lm-green);
  --color-brand-text: var(--lm-brand-text);
  --color-primary: var(--lm-primary);
  --color-on-primary: var(--lm-on-primary);
  --color-spark: var(--lm-spark);
  --font-display: var(--lm-font-display);
  --font-sans: var(--lm-font-body);
  --font-mono: var(--lm-font-mono);
}
```

Tailwind v3 (`tailwind.config.js` → `theme.extend`):

```js
colors: {
  bg: "var(--lm-bg)", surface: "var(--lm-surface)", border: "var(--lm-border)",
  fg: "var(--lm-text)", muted: "var(--lm-text-muted)", brand: "var(--lm-green)",
  "brand-text": "var(--lm-brand-text)", primary: "var(--lm-primary)",
  "on-primary": "var(--lm-on-primary)", spark: "var(--lm-spark)",
},
fontFamily: {
  display: ["var(--lm-font-display)"], sans: ["var(--lm-font-body)"], mono: ["var(--lm-font-mono)"],
},
borderRadius: { sm: "8px", md: "12px", lg: "16px", xl: "24px" },
```

If the app uses shadcn/ui, point its CSS variables (`--background`, `--foreground`, `--primary`, `--border`, etc.) at the matching `--lm-*` tokens rather than editing each component.

## Voice & tone

Plain, confident, local. Short sentences. Say what the product does ("Answers every call, day or night"), avoid hype words.
