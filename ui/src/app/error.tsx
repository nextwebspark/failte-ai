"use client";

import * as Sentry from "@sentry/nextjs";
import { Home, RotateCcw, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { FriendlyNotice } from "@/components/layout/FriendlyNotice";
import { useOwnsPageHeading } from "@/components/layout/pageHeading";
import { Button } from "@/components/ui/button";

/**
 * A screen that crashed while drawing. The app header and nav stay, so the
 * owner can carry on; the details go to Sentry, never onto the screen.
 */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useOwnsPageHeading();
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <FriendlyNotice
      icon={TriangleAlert}
      tone="danger"
      title="Something went wrong on this page"
      actions={
        <>
          <Button onClick={() => reset()}>
            <RotateCcw aria-hidden />
            Try again
          </Button>
          <Button variant="outline" asChild>
            <Link href="/overview">
              <Home aria-hidden />
              Go to Overview
            </Link>
          </Button>
        </>
      }
    >
      It&apos;s not something you did. Try again, and if it keeps happening, let us know and we&apos;ll sort it out.
    </FriendlyNotice>
  );
}
