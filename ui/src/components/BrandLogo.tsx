import { cn } from "@/lib/utils";

// Reusable Failte AI lockup. `mark` renders the square icon on its own (app
// sidebar header); the default renders icon + wordmark. Pass `inverse` to force
// light type on an always-dark surface (e.g. the auth brand panel). Height is
// controlled by the caller via className (e.g. "h-7"); the icon tracks that
// height and the type is sized to sit with it.
//
// ---------------------------------------------------------------------------
// SWAPPING IN REAL ARTWORK
// ---------------------------------------------------------------------------
// The icon is a placeholder at `public/brand/failte-mark.svg` — a voice
// waveform in a rounded badge, kept simple so it survives 16px. To replace it,
// overwrite that file (same viewBox) and `src/app/icon.svg`, which is the same
// artwork serving as the browser-tab icon via Next's app-router convention.
//
// If a designed wordmark lockup arrives as a single image, drop it in
// `public/brand/` and swap the <span> below for an <img> pair — one with
// `dark:hidden` and one with `hidden dark:block` — so the theme picks the ink.
//
// BrandLogo is used in exactly two places: AppSidebar renders `mark`, AuthShell
// renders the wordmark and its inverse.
export function BrandLogo({
  className,
  inverse = false,
  mark = false,
}: {
  className?: string;
  inverse?: boolean;
  mark?: boolean;
}) {
  if (mark) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src="/brand/failte-mark.svg"
        alt="Failte AI"
        className={cn("aspect-square w-auto select-none", className)}
      />
    );
  }

  return (
    <span className={cn("inline-flex select-none items-center gap-2", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/brand/failte-mark.svg" alt="" aria-hidden className="h-full w-auto" />
      <span
        className={cn(
          "whitespace-nowrap text-xl font-semibold leading-none tracking-tight",
          inverse ? "text-white" : "text-foreground",
        )}
      >
        Failte<span className="ml-[0.25em] font-normal opacity-70">AI</span>
      </span>
    </span>
  );
}
