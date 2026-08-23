"use client";

import { Moon, Sun } from "lucide-react";
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
  // Start with null to avoid hydration mismatch - theme is set by inline script in layout.tsx
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);

  useEffect(() => {
    // Read the current theme from the DOM (already set by inline script in layout.tsx)
    const isDark = document.documentElement.classList.contains("dark");
    setTheme(isDark ? "dark" : "light");
  }, []);

  const toggleTheme = () => {
    const newTheme = theme === "light" ? "dark" : "light";
    setTheme(newTheme);
    localStorage.setItem("theme", newTheme);
    document.documentElement.classList.toggle("dark", newTheme === "dark");
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
