import { Loader2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/** Centered heading + message used by the link-landing auth pages. */
export function AuthStatus({
  title,
  message,
  action,
  busy = false,
}: {
  title: string;
  message: string;
  action?: { href: string; label: string };
  /** Show a spinner: the page is working and will move on by itself. */
  busy?: boolean;
}) {
  return (
    <div className="space-y-5 text-center">
      {busy && <Loader2 aria-hidden className="mx-auto size-6 animate-spin text-muted-foreground" />}
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground" role={busy ? "status" : undefined}>
          {message}
        </p>
      </div>
      {action && (
        <Button asChild className="w-full">
          <Link href={action.href}>{action.label}</Link>
        </Button>
      )}
    </div>
  );
}
