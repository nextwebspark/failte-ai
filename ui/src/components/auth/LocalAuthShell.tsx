import type { ReactNode } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { SupportLink } from "@/components/SupportLink";
import { BRAND } from "@/config/brand";

const LEGAL_LINK = "underline underline-offset-4 hover:text-foreground";

/** AuthShell with the standard contact CTA and the legal links, for the
 *  local-auth pages. */
export function LocalAuthShell({ children }: { children: ReactNode }) {
  return (
    <AuthShell
      contactSlot={
        <SupportLink
          label="Talk to us"
          variant="outline"
          className="w-full border-white/20 bg-white/5 text-zinc-100 hover:bg-white/10 hover:text-white"
        />
      }
    >
      {children}
      <p className="text-center text-xs text-muted-foreground">
        By continuing, you agree to the{" "}
        <a href={BRAND.termsUrl} target="_blank" rel="noopener noreferrer" className={LEGAL_LINK}>
          Terms of Service
        </a>{" "}
        and{" "}
        <a href={BRAND.privacyUrl} target="_blank" rel="noopener noreferrer" className={LEGAL_LINK}>
          Privacy Policy
        </a>
        .
      </p>
    </AuthShell>
  );
}
