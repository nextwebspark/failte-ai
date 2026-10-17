"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ThemeToggleProps {
  className?: string;
  /**
   * Render the canvas's nav row: full-width, left aligned, labelled with the
   * theme it switches TO ("Dark mode" while light) — see the sidebar footer in
   * app-doc/claude-design/Failte AI v2.dc.html.
   */
  showLabel?: boolean;
  variant?: "ghost" | "outline" | "default";
  size?: "default" | "sm" | "lg" | "icon";
}

export default function ThemeToggle({
  className,
  showLabel = false,
  variant = "ghost",
  size = "icon"
}: ThemeToggleProps) {
  // next-themes owns the theme: it follows the OS until the user picks one
  // here, then stores that choice under "theme" (the key the inline script in
  // layout.tsx reads before hydration). Going through setTheme keeps its
  // system listener in step, so an OS change can't undo an explicit choice.
  const { resolvedTheme, setTheme } = useTheme();
  // resolvedTheme is only known on the client; treat it as unknown until mount
  // so the server render and the first client render agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const theme = mounted && (resolvedTheme === "dark" || resolvedTheme === "light")
    ? resolvedTheme
    : null;

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  // The icon shows the destination too: a moon while the app is light.
  const icon = theme === "dark"
    ? <Sun className="h-4 w-4 shrink-0" />
    : <Moon className="h-4 w-4 shrink-0" />;

  if (showLabel) {
    return (
      <Button
        variant={variant}
        size={size === "icon" ? "default" : size}
        className={cn("w-full justify-start gap-2.5 font-normal", className)}
        onClick={toggleTheme}
      >
        {/* Theme is only known after mount; hide rather than print the wrong
            destination for a frame. */}
        <span className={cn("flex items-center gap-2.5", theme === null && "invisible")}>
          {icon}
          <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
        </span>
      </Button>
    );
  }

  return (
    <Button
      variant={variant}
      size={size}
      className={className}
      onClick={toggleTheme}
    >
      {icon}
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
