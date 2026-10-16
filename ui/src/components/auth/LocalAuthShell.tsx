import type { ReactNode } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { SupportLink } from "@/components/SupportLink";

/** AuthShell with the standard contact CTA, for the local-auth pages. */
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
    </AuthShell>
  );
}
