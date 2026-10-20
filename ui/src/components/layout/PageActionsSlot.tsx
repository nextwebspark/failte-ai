"use client";

import React, { createContext, type ReactNode, useContext, useState } from "react";
import { createPortal } from "react-dom";

/**
 * The canvas puts a screen's primary action in the app HEADER, next to the
 * breadcrumb, rather than above the content. Pages stay in charge of their own
 * buttons — they just render them through <PageActions>, which portals them
 * into the slot the top bar exposes.
 *
 * The slot element is only known after the top bar mounts, so the portal is a
 * no-op on the server and on the first client render; the buttons appear as
 * soon as the header ref lands. Nothing else about a page's behaviour changes.
 */
const PageActionsSlotContext = createContext<HTMLElement | null>(null);

export function PageActionsSlotProvider({
  children,
  slot,
}: {
  children: ReactNode;
  slot: HTMLElement | null;
}) {
  return (
    <PageActionsSlotContext.Provider value={slot}>
      {children}
    </PageActionsSlotContext.Provider>
  );
}

/** Held by the top bar; hands the mounted node back to the provider. */
export function usePageActionsSlotState() {
  return useState<HTMLElement | null>(null);
}

export function PageActions({ children }: { children: ReactNode }) {
  const slot = useContext(PageActionsSlotContext);

  if (!slot) {
    return null;
  }

  return createPortal(
    // Screens give their buttons `size="toolbar"` to match the header.
    <div className="flex flex-wrap items-center gap-2 md:flex-nowrap">{children}</div>,
    slot,
  );
}
