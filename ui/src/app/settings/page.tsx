"use client";


import { CallEventsSection } from "@/components/CallEventsSection";
import { MCPSection } from "@/components/MCPSection";
import { OrganizationPreferencesSection } from "@/components/OrganizationPreferencesSection";
import { DangerZoneCard } from "@/components/privacy/DangerZoneCard";
import { YourAccountCard } from "@/components/privacy/YourAccountCard";
import { TelemetrySection } from "@/components/TelemetrySection";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { BRAND } from "@/config/brand";
import { useOrgConfig } from "@/context/OrgConfigContext";

export default function SettingsPage() {
  // Organization-wide defaults are admin-only; the rest are integrations.
  const { can, orgContext } = useOrgConfig();
  const canManageOrg = can("org:manage");
  // A pending deletion closes everything but the account and danger zone.
  const pendingDeletion = Boolean(orgContext?.deletion?.pending);

  if (pendingDeletion) {
    return (
      <div className="page-body">
        <div className="w-full max-w-2xl space-y-6">
          {canManageOrg && <DangerZoneCard />}
          <YourAccountCard />
        </div>
      </div>
    );
  }

  return (
    <div className="page-body">
      {/* Screen name and strapline are rendered by the app header (AppTopBar). */}
      <div className="w-full max-w-2xl space-y-6">
        {canManageOrg && (
        <Card>
          <CardHeader>
            <CardTitle>Preferences</CardTitle>
            <CardDescription>
              Set organization-wide defaults such as the test phone number and
              timezone.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <OrganizationPreferencesSection />
          </CardContent>
        </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>MCP Server</CardTitle>
            <CardDescription>
              Let AI agents access your {BRAND.name} workspace and documentation via
              the Model Context Protocol.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <MCPSection />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Telemetry</CardTitle>
            <CardDescription>
              Configure Langfuse tracing for your voice agent calls.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TelemetrySection />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Call events</CardTitle>
            <CardDescription>Configure where your organization sends call diagnostics.</CardDescription>
          </CardHeader>
          <CardContent>
            <CallEventsSection />
          </CardContent>
        </Card>

        <YourAccountCard />
        {canManageOrg && <DangerZoneCard />}
      </div>
    </div>
  );
}
