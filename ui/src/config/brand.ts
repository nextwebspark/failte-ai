// Single source of truth for the product's name, domain and contact points.
// UI copy must read from here rather than hard-coding the brand, so a future
// rename is a one-file change. Artwork lives in public/brand/ (from the brand
// kit in brand-kit/lightmove-brand/) and is rendered through
// components/BrandLogo.tsx.

const shortName = "LightMove";
const tld = ".ai";
const domain = `${shortName.toLowerCase()}${tld}`;

export const BRAND = {
  /** Full product name, as written in copy and page titles. */
  name: `${shortName}${tld}`,
  /** Name without the TLD, for tight spots. */
  shortName,
  tld,
  tagline: "Build, test and deploy voice AI agents",
  domain,
  appUrl: `https://app.${domain}`,
  docsUrl: `https://docs.${domain}`,
  salesEmail: `sales@${domain}`,
  supportEmail: `support@${domain}`,
  assets: {
    /** Square mark: green tile, white voice bars, orange spark. Reads on light and dark. */
    mark: "/brand/lightmove-mark.svg",
    /** White tile with green bars, for green backgrounds. */
    markReversed: "/brand/lightmove-mark-reversed.svg",
    /** Full lockup for light backgrounds (ink wordmark), text outlined. */
    logoLight: "/brand/lightmove-logo-light.svg",
    /** Full lockup for dark backgrounds (white wordmark, Mint ".ai"), text outlined. */
    logoDark: "/brand/lightmove-logo-dark.svg",
    /** Raster card for link previews (OpenGraph). */
    ogImage: { url: "/brand/lightmove-og.png", width: 1200, height: 630 },
  },
} as const;
