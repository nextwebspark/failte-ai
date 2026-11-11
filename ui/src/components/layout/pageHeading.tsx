"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * One h1 per screen. The app header prints the screen's name as the h1 by
 * default; a screen that shows its own title in the page (PageHeader, the
 * Overview greeting, the Settings frame) claims the h1 with
 * `useOwnsPageHeading()`, and the header then prints its name as plain text
 * and drops the strapline the page already shows.
 *
 * Screens that don't claim it keep exactly the old behaviour.
 */
type PageHeadingState = {
  owned: boolean;
  claim: () => () => void;
};

const PageHeadingContext = createContext<PageHeadingState | null>(null);

export function PageHeadingProvider({ children }: { children: ReactNode }) {
  const [claims, setClaims] = useState(0);
  const claim = useCallback(() => {
    setClaims((n) => n + 1);
    return () => setClaims((n) => Math.max(0, n - 1));
  }, []);
  const value = useMemo<PageHeadingState>(() => ({ owned: claims > 0, claim }), [claims, claim]);
  return <PageHeadingContext.Provider value={value}>{children}</PageHeadingContext.Provider>;
}

/** True while the open screen prints its own h1. */
export function usePageHeadingOwned(): boolean {
  return useContext(PageHeadingContext)?.owned ?? false;
}

/** Call from a screen that renders its own h1. Safe outside the shell. */
export function useOwnsPageHeading(): void {
  const claim = useContext(PageHeadingContext)?.claim;
  useEffect(() => claim?.(), [claim]);
}
