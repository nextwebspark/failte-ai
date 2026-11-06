"use client";

import { SlidersHorizontal } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { OrganizationPreferencesSection } from "@/components/OrganizationPreferencesSection";
import { DangerZoneCard } from "@/components/privacy/DangerZoneCard";
import { YourAccountCard } from "@/components/privacy/YourAccountCard";
import { SettingsSection } from "@/components/settings/SettingsLayout";
import { firstSettingsUrl } from "@/components/settings/settingsNav";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { useOrgConfig } from "@/context/OrgConfigContext";

import { OrganizationNameCard } from "../team/OrganizationNameCard";

/**
 * Workspace > General: the workspace's name and organization-wide defaults,
 * for admins. Anyone else who lands here (an old link to Workspace settings)
 * is sent to the first settings screen they can use; MCP, telemetry and call
 * events moved to Settings > MCP & telemetry.
 */
export default function SettingsPage() {
  const router = useRouter();
  const { role, can, orgContext } = useOrgConfig();
  const canManageOrg = can("org:manage");
  // A pending deletion closes everything but the account and danger zone.
  const pendingDeletion = Boolean(orgContext?.deletion?.pending);
  const redirect = role !== null && !canManageOrg && !pendingDeletion;

  useEffect(() => {
    if (redirect) router.replace(firstSettingsUrl(can));
  }, [redirect, router, can]);

  if (pendingDeletion) {
    return (
      <div className="page-body">
        <div className="w-full space-y-6">
          {canManageOrg && <DangerZoneCard />}
          <YourAccountCard />
        </div>
      </div>
    );
  }

  // Still finding out who you are: hold the screen's shape, don't go blank.
  if (role === null) return <PageSkeleton variant="settings" withHeader={false} />;
  if (!canManageOrg) return null;

  return (
    <div className="page-body">
      <div className="flex w-full flex-col gap-[18px]">
        <OrganizationNameCard />
        <SettingsSection
          id="defaults"
          icon={SlidersHorizontal}
          title="Defaults and call reporting"
          description="Used by test calls, schedules and the outcomes your reports and webhooks show."
        >
          <OrganizationPreferencesSection show="general" />
        </SettingsSection>
      </div>
    </div>
  );
}
