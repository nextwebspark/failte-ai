import { cn } from "@/lib/utils";

// Reusable Failte AI wordmark. Theme-aware by default: dark ink on light
// surfaces, light ink on dark. Pass `inverse` to force the light treatment on an
// always-dark surface (e.g. the auth brand panel). Pass `mark` to render the
// square monogram instead of the full wordmark (e.g. the app sidebar header).
// Height is controlled by the caller via className (e.g. "h-7"); the wordmark
// sizes its type off that height so each lockup keeps its proportions.
//
// ---------------------------------------------------------------------------
// SWAPPING IN REAL ARTWORK
// ---------------------------------------------------------------------------
// This renders type, not images, so the UI carries our name before the designed
// logo exists. To switch to image assets, drop them in `public/brand/` and
// replace each branch below with the corresponding <img>:
//
//   mark     -> <img src="/brand/failte-mark.png"          alt="Failte AI" className={cn("w-auto select-none", className)} />
//   inverse  -> <img src="/brand/failte-logo-inverse.png"  alt="Failte AI" className={cn("w-auto select-none", className)} />
//   default  -> two <img>s, `dark:hidden` on failte-logo.png and `hidden dark:block`
//               on failte-logo-inverse.png, so the theme picks the right ink.
//
// Nothing else needs to change: BrandLogo is used in exactly two places
// (AppSidebar renders `mark`, AuthShell renders the wordmark and its inverse).
// The browser-tab icon is separate — it is `src/app/favicon.ico`, replaced in
// place by Next's app-router convention.
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
      <span
        aria-label="Failte AI"
        role="img"
        className={cn(
          "inline-flex aspect-square select-none items-center justify-center rounded-md",
          "bg-foreground text-background text-[0.7rem] font-semibold leading-none",
          className,
        )}
      >
        FA
      </span>
    );
  }

  return (
    <span
      aria-label="Failte AI"
      role="img"
      className={cn(
        "inline-flex select-none items-center whitespace-nowrap text-xl font-semibold leading-none tracking-tight",
        inverse ? "text-white" : "text-foreground",
        className,
      )}
    >
      Failte<span className="ml-[0.25em] font-normal opacity-70">AI</span>
    </span>
  );
}
