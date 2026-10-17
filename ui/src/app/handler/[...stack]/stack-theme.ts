// Dark token overrides for the embedded Stack Auth form so it blends into the
// auth card surface. These mirror the dark palette in globals.css — the
// forest-tinted panel/line/ink surfaces with the brand green on the primary
// button and on the focus ring. Stack's theme parser does not accept OKLCH strings, so keep
// these values in hex and update them whenever the .dark block changes.

import type { StackTheme } from "@stackframe/stack";
import type { ComponentProps } from "react";

type ThemeConfig = NonNullable<ComponentProps<typeof StackTheme>["theme"]>;

export const stackAuthDarkTheme: ThemeConfig = {
  dark: {
    background: "#111714", // --panel
    foreground: "#eef3f0", // --ink
    card: "#111714",
    cardForeground: "#eef3f0",
    popover: "#111714",
    popoverForeground: "#eef3f0",
    primary: "#3ddc97", // --brand
    primaryForeground: "#0a1f17", // --brand-ink
    secondary: "#161d19", // --panel-2
    secondaryForeground: "#eef3f0",
    muted: "#161d19",
    mutedForeground: "#87958d", // --ink-3
    accent: "#161d19",
    accentForeground: "#eef3f0",
    destructive: "#e5534b", // canvas --red
    destructiveForeground: "#ffffff",
    border: "#243029", // --line
    input: "#243029",
    ring: "#3ddc97", // --brand
  },
  radius: "0.75rem",
};
