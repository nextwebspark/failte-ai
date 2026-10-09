import { BRAND } from "@/config/brand";
import { cn } from "@/lib/utils";

// Fallcha.ai lockup, from the official brand kit (brand-kit/, copied into
// public/brand/). `mark` renders the call-bubble icon on its own (sidebar and
// top bar); the default renders the full lockup. Height is set by the caller
// via className (e.g. "h-7"); width follows the artwork's aspect ratio.
//
// The kit ships the lockup in two inks and forbids the light-background logo
// on dark surfaces, so the default renders both and lets the theme pick one.
// Pass `inverse` on surfaces that are dark in every theme (the auth brand
// panel) to force the dark-background lockup. The mark is a single file: its
// green bubble reads on both backgrounds.
//
// Kit rules worth keeping in mind at call sites: the lockup must stay at least
// 24px tall and the mark 16px; leave clear space of half the mark's height.
//
// Used by AppSidebar and AppTopBar (`mark`), AuthShell (default + `inverse`)
// and EventBanner (default).
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
        src={BRAND.assets.mark}
        alt={BRAND.name}
        className={cn("aspect-square w-auto select-none", className)}
      />
    );
  }

  if (inverse) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={BRAND.assets.logoDark}
        alt={BRAND.name}
        className={cn("w-auto select-none", className)}
      />
    );
  }

  return (
    <span className={cn("inline-flex select-none", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={BRAND.assets.logoLight} alt={BRAND.name} className="h-full w-auto dark:hidden" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={BRAND.assets.logoDark}
        alt=""
        aria-hidden
        className="hidden h-full w-auto dark:block"
      />
    </span>
  );
}
