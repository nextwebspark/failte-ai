import { BRAND } from "@/config/brand";
import { cn } from "@/lib/utils";

// LightMove.ai logo, built the way the brand kit asks for in-app use
// (brand-kit/lightmove-brand/BRAND.md, step 7): the mark as an image followed
// by the wordmark as live text — "LightMove" in Sora 600 at -0.03em tracking,
// then ".ai" in the brand-text colour. Live text keeps the wordmark crisp,
// themeable and in the real typeface; the outlined lockup SVGs in
// public/brand/ are for places that cannot load a web font (OG card, docs).
//
// `size` is the mark's height in px and everything else scales from it in the
// kit's proportions: mark 64, wordmark 40, gap 20. `mark` renders the mark on
// its own (collapsed sidebar). Pass `inverse` on surfaces that are dark in
// every theme (the auth brand panel) to pin the dark-background colours.
//
// Kit rules worth keeping in mind at call sites: the mark must stay at least
// 24px and the full logo at least 120px wide; leave clear space of half the
// mark's height.
//
// Used by AppSidebar and AppTopBar, AuthShell (default + `inverse`) and
// EventBanner.
export function BrandLogo({
  className,
  size = 24,
  inverse = false,
  mark = false,
}: {
  className?: string;
  size?: number;
  inverse?: boolean;
  mark?: boolean;
}) {
  if (mark) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={BRAND.assets.mark}
        alt={BRAND.name}
        width={size}
        height={size}
        className={cn("shrink-0 select-none", className)}
        style={{ width: size, height: size }}
      />
    );
  }

  return (
    <span
      translate="no"
      className={cn("inline-flex shrink-0 select-none items-center gap-[0.3125em] leading-none", className)}
      style={{ fontSize: size }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={BRAND.assets.mark} alt="" aria-hidden className="h-[1em] w-[1em] shrink-0" />
      <span
        className={cn(
          "whitespace-nowrap font-display text-[0.625em] font-semibold tracking-[-0.03em]",
          inverse ? "text-[#f2f7f4]" : "text-foreground",
        )}
      >
        {BRAND.shortName}
        <span className={inverse ? "text-[#3ddc97]" : "text-brand"}>{BRAND.tld}</span>
      </span>
    </span>
  );
}
