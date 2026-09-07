"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { isAgentRoute } from "./agentNav";

/**
 * Which chrome a URL gets.
 *
 * A run lives at `/workflow/<id>/run/<runId>` whichever list you opened it
 * from, so the path alone can't say whether the user is inside an agent or
 * still in the workspace. Every link into a run therefore carries the list it
 * came from as `?from=<path+query>`, and that decides two things:
 *
 *   - the nav panel and the breadcrumb stay where the user was (workspace nav
 *     when `from` is a workspace list, agent nav otherwise), and
 *   - the back link returns to that exact list, filters and page included.
 *
 * The test rail is never shown on a run: a finished run is a read-only record,
 * not a live session.
 */

export const RETURN_TO_PARAM = "from";

/** `/workflow/1/run/92` — a single run's detail screen. */
const RUN_DETAIL_ROUTE = /^\/workflow\/\d+\/run\/\d+\/?$/;

export function isRunDetailRoute(pathname: string): boolean {
  return RUN_DETAIL_ROUTE.test(pathname);
}

/**
 * A `from` value we're willing to navigate to: a same-origin relative path.
 * Anything else (absolute URL, protocol-relative `//host`, a bare word) is
 * dropped so a hand-edited URL can't turn the back link into an open redirect.
 */
export function safeReturnTo(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/")) return null;
  if (raw.startsWith("//")) return null;
  if (raw.includes("\\")) return null;
  return raw;
}

/**
 * Link to a run, remembering the list it was opened from. Pass `returnTo` as
 * the caller's own path + query so the back link restores the list exactly as
 * the user left it (page, sort, filters).
 */
export function runDetailHref(
  workflowId: number | string,
  runId: number | string,
  returnTo?: string | null,
): string {
  const href = `/workflow/${workflowId}/run/${runId}`;
  const safe = safeReturnTo(returnTo);
  return safe ? `${href}?${RETURN_TO_PARAM}=${encodeURIComponent(safe)}` : href;
}

export type ShellChrome = {
  /** The validated list URL this screen was opened from, or null. */
  returnTo: string | null;
  /** `from` points at a workspace screen — keep the workspace nav and header. */
  workspaceMode: boolean;
  /** The agent test rail belongs on this route. */
  showTestRail: boolean;
};

/**
 * Safe to call from the shell: the root layout already wraps AppLayout in a
 * Suspense boundary (src/app/layout.tsx), which is what `useSearchParams`
 * needs.
 */
export function useShellChrome(): ShellChrome {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const returnTo = safeReturnTo(searchParams.get(RETURN_TO_PARAM));
  const workspaceMode = returnTo !== null && !isAgentRoute(returnTo);

  return {
    returnTo,
    workspaceMode,
    showTestRail:
      isAgentRoute(pathname) && !workspaceMode && !isRunDetailRoute(pathname),
  };
}
