"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

/**
 * Stands in for every screen when there is no organization to work in: the
 * selected one was erased, or the user no longer belongs to any.
 */
export function NoOrganizationNotice({ reason }: { reason: "erased" | "none" }) {
  const { logout, provider } = useAuth();
  const switcher =
    provider === "stack"
      ? "Pick another team in the switcher in the sidebar"
      : "Use the workspace switcher at the top to create a new organization or pick another one";

  return (
    <div className="page-body">
      <div className="max-w-xl space-y-3 text-sm">
        <h2 className="text-lg font-semibold">
          {reason === "erased"
            ? "This organization has been deleted"
            : "You don't belong to an organization"}
        </h2>
        <p className="text-muted-foreground">
          {reason === "erased"
            ? "Its data has been permanently erased. "
            : "The organization you were in may have been deleted, or you were removed from it. "}
          {switcher}, or sign out.
          {provider !== "stack" && (
            <>
              {" "}
              You can also export or delete your account in{" "}
              <Link href="/account" className="underline">
                Your account
              </Link>
              .
            </>
          )}
        </p>
        <Button variant="outline" onClick={() => void logout()}>
          <LogOut />
          Sign out
        </Button>
      </div>
    </div>
  );
}
