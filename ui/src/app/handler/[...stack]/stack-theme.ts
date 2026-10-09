// Dark token overrides for the embedded Stack Auth form so it blends into the
// auth card surface. These mirror the dark palette in globals.css — the canvas
// panel/line/ink surfaces with the brand green on the primary button and the sky
// blue focus ring. Stack's theme parser does not accept OKLCH strings, so keep
// these values in hex and update them whenever the .dark block changes.

import type { StackTheme } from "@stackframe/stack";
import type { ComponentProps } from "react";

type ThemeConfig = NonNullable<ComponentProps<typeof StackTheme>["theme"]>;

export const stackAuthDarkTheme: ThemeConfig = {
  dark: {
    background: "#12151b", // --panel
    foreground: "#f1f3f6", // --ink
    card: "#12151b",
    cardForeground: "#f1f3f6",
    popover: "#12151b",
    popoverForeground: "#f1f3f6",
    primary: "#4fd49a", // --brand
    primaryForeground: "#071f17", // --brand-ink
    secondary: "#171b22", // --panel-2
    secondaryForeground: "#f1f3f6",
    muted: "#171b22",
    mutedForeground: "#8d96a6", // --ink-3
    accent: "#171b22",
    accentForeground: "#f1f3f6",
    destructive: "#e5534b", // canvas --red
    destructiveForeground: "#ffffff",
    border: "#232833", // --line
    input: "#232833",
    ring: "#5cb3ff", // --sky
  },
  radius: "0.625rem",
};
