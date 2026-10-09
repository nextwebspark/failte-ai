// Single source of truth for the product's name, domain and contact points.
// UI copy must read from here rather than hard-coding the brand, so a future
// rename is a one-file change. Artwork lives in public/brand/ (from the brand
// kit in brand-kit/) and is rendered through components/BrandLogo.tsx.

const shortName = "Fallcha";
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
    /** Square mark; transparent background, reads on light and dark. */
    mark: "/brand/fallcha-mark.svg",
    /** Full lockup for light backgrounds (Forest ink wordmark). */
    logoLight: "/brand/fallcha-logo-light.svg",
    /** Full lockup for dark backgrounds (white wordmark, Mint ".ai"). */
    logoDark: "/brand/fallcha-logo-dark.svg",
    /** Raster lockup for link previews (OpenGraph). */
    ogImage: "/brand/fallcha-logo-light.png",
  },
} as const;
