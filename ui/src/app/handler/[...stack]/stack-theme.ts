// Dark token overrides for the embedded Stack Auth form so it blends into the
// auth card surface. These mirror the dark palette in globals.css — the
// Uncava dark surfaces (cool near-black panel, white-alpha hairlines, cool
// grey ink) with the brand green on the primary button and the focus ring. Stack's theme parser does not accept OKLCH strings, so keep
// these values in hex and update them whenever the .dark block changes.

import type { StackTheme } from "@stackframe/stack";
import type { ComponentProps } from "react";

type ThemeConfig = NonNullable<ComponentProps<typeof StackTheme>["theme"]>;

export const stackAuthDarkTheme: ThemeConfig = {
  dark: {
    background: "#0e1013", // --panel
    foreground: "#f4f6f8", // --ink
    card: "#0e1013",
    cardForeground: "#f4f6f8",
    popover: "#0e1013",
    popoverForeground: "#f4f6f8",
    primary: "#3ddc97", // --brand
    primaryForeground: "#0a1f17", // --brand-ink
    secondary: "#15181d", // --panel-2
    secondaryForeground: "#f4f6f8",
    muted: "#15181d",
    mutedForeground: "#7c8493", // --ink-3
    accent: "#15181d",
    accentForeground: "#f4f6f8",
    destructive: "#e5534b", // canvas --red
    destructiveForeground: "#ffffff",
    border: "#1f2226", // --line (rgba(255,255,255,.08) on --panel)
    input: "#30333a", // --input (rgba(255,255,255,.14) on --panel)
    ring: "#3ddc97", // --brand
  },
  radius: "0.75rem",
};
