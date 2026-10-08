import type { OrgRole, Permission } from "@/client/types.gen";

export type { OrgRole, Permission };

/** Display names. The stored role values never change when these do. */
export const ROLE_LABELS: Record<OrgRole, string> = {
  admin: "Admin",
  developer: "Developer",
  viewer: "Client",
};

export const ROLE_DESCRIPTIONS: Record<OrgRole, string> = {
  admin: "Everything, including members, billing and workspace settings.",
  developer: "Builds and configures agents, telephony, integrations and API keys.",
  viewer: "Read-only: call history, recordings, reports and usage.",
};

export const ORG_ROLES: readonly OrgRole[] = ["admin", "developer", "viewer"];
