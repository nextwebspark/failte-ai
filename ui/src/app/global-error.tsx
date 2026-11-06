"use client";

import "./globals.css";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

/**
 * The last line of defence: the app's own frame failed to draw, so this page
 * brings its own <html>. Plain and friendly, with no error text on screen —
 * the details go to Sentry.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body className="bg-background font-sans text-foreground antialiased">
        <main className="flex min-h-svh items-center justify-center p-6">
          <div className="flex max-w-md flex-col items-center text-center">
            <h1 className="text-xl font-bold">Something went wrong</h1>
            <p className="mt-2 text-[14.5px] leading-relaxed text-ink-2">
              It&apos;s not something you did. Try again, and if it keeps happening, let us know and
              we&apos;ll sort it out.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2.5">
              <button
                type="button"
                onClick={() => reset()}
                className="h-10 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
              >
                Try again
              </button>
              {/* A full page load on purpose: the app's frame is what failed. */}
              <a
                href="/overview"
                className="inline-flex h-10 items-center rounded-md border border-line px-4 text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
              >
                Go to Overview
              </a>
            </div>
          </div>
        </main>
      </body>
    </html>
  );
}
