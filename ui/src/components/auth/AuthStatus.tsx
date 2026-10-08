import Link from "next/link";

import { Button } from "@/components/ui/button";

/** Centered heading + message used by the link-landing auth pages. */
export function AuthStatus({
  title,
  message,
  action,
}: {
  title: string;
  message: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="space-y-5 text-center">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
      {action && (
        <Button asChild className="w-full">
          <Link href={action.href}>{action.label}</Link>
        </Button>
      )}
    </div>
  );
}
