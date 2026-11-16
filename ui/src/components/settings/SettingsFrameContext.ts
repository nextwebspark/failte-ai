"use client";

import { createContext, useContext } from "react";

/**
 * True inside the Settings frame (SettingsShell), which already prints the
 * screen's title, description and scope. A screen's own PageHeader then
 * leaves its title out, so it isn't shown twice.
 */
export const SettingsFrameContext = createContext(false);

export function useInSettingsFrame(): boolean {
  return useContext(SettingsFrameContext);
}
