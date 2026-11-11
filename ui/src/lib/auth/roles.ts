import type { OrgRole, Permission } from "@/client/types.gen";

export type { OrgRole, Permission };

/** Display names. The stored role values never change when these do. */
export const ROLE_LABELS: Record<OrgRole, string> = {
  admin: "Admin",
  developer: "Developer",
  viewer: "Owner",
  staff: "Staff",
};

export const ROLE_DESCRIPTIONS: Record<OrgRole, string> = {
  admin: "Everything, including members, billing and workspace settings.",
  developer: "Builds and configures agents, telephony, integrations and API keys.",
  viewer: "The business owner: sees everything, runs bookings and decides which staff can too.",
  staff: "View-only: calls, bookings and reports. The owner can let them manage bookings.",
};

export const ORG_ROLES: readonly OrgRole[] = ["admin", "developer", "viewer", "staff"];
