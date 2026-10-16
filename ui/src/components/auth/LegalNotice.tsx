import { BRAND } from "@/config/brand";

const LINK_CLASS = "underline underline-offset-4 hover:text-foreground";

/** "By continuing, you agree to…" for the pages where signing in or signing
 *  up happens. Links open in a new tab so a half-filled form survives. */
export function LegalNotice() {
  return (
    <p className="text-center text-xs text-muted-foreground">
      By continuing, you agree to the{" "}
      <a href={BRAND.termsUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
        Terms of Service<span className="sr-only"> (opens in a new tab)</span>
      </a>{" "}
      and{" "}
      <a href={BRAND.privacyUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
        Privacy Policy<span className="sr-only"> (opens in a new tab)</span>
      </a>
      .
    </p>
  );
}
