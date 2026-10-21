"use client";

import { DangerZoneCard } from "@/components/privacy/DangerZoneCard";
import { YourAccountCard } from "@/components/privacy/YourAccountCard";
import { useOrgConfig } from "@/context/OrgConfigContext";

/**
 * Your account and data, open to every member (Workspace settings needs a
 * role that can read integrations). Admins also get the organization's
 * export and deletion here.
 */
export default function AccountPage() {
  const { can } = useOrgConfig();

  return (
    <div className="page-body">
      <div className="w-full max-w-2xl space-y-6">
        <YourAccountCard />
        {can("org:manage") && <DangerZoneCard />}
      </div>
    </div>
  );
}
