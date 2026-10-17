"use client";

// Thin wrapper around next-themes so the root (server) layout can mount a theme
// provider without pulling client-only code into the server module graph. The
// theme follows the OS until the user picks one with ThemeToggle; that choice
// is stored under the "theme" key and wins from then on.

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

export function ThemeProvider({ children, ...props }: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
