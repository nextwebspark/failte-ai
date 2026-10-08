import { Lock } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { type OrgRole,ROLE_LABELS } from "@/lib/auth/roles";

/** Shown in place of a screen the caller's role cannot use. */
export function NoAccess({ role }: { role: OrgRole | null }) {
  return (
    <div className="page-body">
      <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
        <Lock className="h-8 w-8 text-ink-3" aria-hidden />
        <div className="space-y-1.5">
          <h2 className="text-lg font-semibold">You don&apos;t have access to this page</h2>
          <p className="text-sm text-muted-foreground">
            {role ? `Your role is ${ROLE_LABELS[role]}. ` : ""}
            Ask a workspace admin if you need access.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/overview">Go to overview</Link>
        </Button>
      </div>
    </div>
  );
}
