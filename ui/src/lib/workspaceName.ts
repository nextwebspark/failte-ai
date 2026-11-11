/**
 * What a workspace is called on screen. A workspace created without a name
 * (the API returns `null`) is shown as "My workspace" everywhere: the
 * switcher in the header, Your account, and the name box on Settings.
 */
export const DEFAULT_WORKSPACE_NAME = "My workspace";

export function workspaceDisplayName(name: string | null | undefined): string {
  const trimmed = name?.trim();
  return trimmed ? trimmed : DEFAULT_WORKSPACE_NAME;
}
