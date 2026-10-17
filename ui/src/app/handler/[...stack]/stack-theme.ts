// Dark token overrides for the embedded Stack Auth form so it blends into the
// auth card surface. These mirror the dark palette in globals.css — the
// neutral black panel/line/ink surfaces with the brand green on the primary
// button and on the focus ring. Stack's theme parser does not accept OKLCH strings, so keep
// these values in hex and update them whenever the .dark block changes.

import type { StackTheme } from "@stackframe/stack";
import type { ComponentProps } from "react";

type ThemeConfig = NonNullable<ComponentProps<typeof StackTheme>["theme"]>;

export const stackAuthDarkTheme: ThemeConfig = {
  dark: {
    background: "#111111", // --panel
    foreground: "#f2f2f2", // --ink
    card: "#111111",
    cardForeground: "#f2f2f2",
    popover: "#111111",
    popoverForeground: "#f2f2f2",
    primary: "#3ddc97", // --brand
    primaryForeground: "#0a1f17", // --brand-ink
    secondary: "#171717", // --panel-2
    secondaryForeground: "#f2f2f2",
    muted: "#171717",
    mutedForeground: "#8f8f8f", // --ink-3
    accent: "#171717",
    accentForeground: "#f2f2f2",
    destructive: "#e5534b", // canvas --red
    destructiveForeground: "#ffffff",
    border: "#262626", // --line
    input: "#262626",
    ring: "#3ddc97", // --brand
  },
  radius: "0.75rem",
};
