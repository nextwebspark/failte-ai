"use client";

import { Clock, ExternalLink, FileText, Megaphone, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getPreferencesApiV1OrganizationsPreferencesGet } from "@/client/sdk.gen";
import { OrganizationPreferencesSection } from "@/components/OrganizationPreferencesSection";
import { CallerDataRequestDialog } from "@/components/privacy/CallerDataRequestDialog";
import { DangerZoneCard } from "@/components/privacy/DangerZoneCard";
import { SettingBlock, SettingRow, SettingsSection } from "@/components/settings/SettingsLayout";
import { BRAND } from "@/config/brand";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";

import { AgentDisclosureList } from "./AgentDisclosureList";

const LEGAL_DOCUMENTS = [
  { label: "Privacy Policy", href: BRAND.privacyUrl },
  { label: "Terms of Service", href: BRAND.termsUrl },
  { label: "Data Processing Agreement", href: BRAND.dpaUrl },
  { label: "Sub-processors", href: BRAND.subprocessorsUrl },
  { label: "Cookie Policy", href: BRAND.cookiesUrl },
];

/** The period for members who can see it but not change it (saving is admin-only). */
function RetentionReadOnly() {
  const { user, loading: authLoading } = useAuth();
  const hasFetched = useRef(false);
  const [days, setDays] = useState<number | null | "error">(null);

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;
    void getPreferencesApiV1OrganizationsPreferencesGet().then((result) =>
      setDays(result.error || !result.data ? "error" : result.data.call_data_retention_days ?? 90),
    );
  }, [authLoading, user]);

  return (
    <SettingRow
      label="Call data retention"
      hint="Recordings, transcripts and call details are permanently deleted after this period. Only an admin can change it."
      compact
    >
      <span className="font-mono text-[13px] text-foreground">
        {days === null ? "…" : days === "error" ? "Unavailable" : `${days} days`}
      </span>
    </SettingRow>
  );
}

/**
 * Compliance > Privacy & compliance. Gathers what the platform already does
 * for GDPR and the AI notice in one place: how long call data is kept, which
 * agents tell callers they are talking to an AI, answering a caller's
 * access or erasure request, the workspace's export and deletion, and the
 * legal documents. Nothing here is new behaviour; each control is the one
 * used elsewhere.
 */
export default function ComplianceSettingsPage() {
  const { can } = useOrgConfig();
  const isAdmin = can("org:manage");

  return (
    <div className="page-body">
      <div className="flex w-full flex-col gap-[18px]">
        <SettingsSection
          id="retention"
          icon={Clock}
          tone="brand"
          title="Data retention"
          description="How long call recordings, transcripts and call details are kept."
        >
          {isAdmin ? <OrganizationPreferencesSection show="retention" /> : <RetentionReadOnly />}
        </SettingsSection>

        <SettingsSection
          id="disclosure"
          icon={Megaphone}
          tone="sky"
          title="AI and recording notice"
          description="At the start of a call each agent can tell the caller they are speaking with an AI and that the call may be recorded."
        >
          <AgentDisclosureList />
        </SettingsSection>

        <SettingsSection
          id="caller-requests"
          icon={ShieldCheck}
          title="Caller data requests"
          description="When a caller asks for a copy of their data, or for it to be deleted."
          action={isAdmin ? <CallerDataRequestDialog /> : undefined}
        >
          <SettingBlock>
            <p className="text-[13px] text-ink-2">
              {isAdmin
                ? "Look a caller up by phone number to export their calls or permanently delete them. The same tool is on Calls."
                : "Only an admin can export or delete a caller's data. Ask an admin of this workspace."}
            </p>
          </SettingBlock>
        </SettingsSection>

        <SettingsSection
          id="legal"
          icon={FileText}
          title="Legal documents"
          description={`The terms ${BRAND.name} works under, and what it does with personal data.`}
        >
          <ul className="divide-y divide-line-soft">
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.href}>
                <a
                  href={doc.href}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between gap-3 px-[18px] py-3 text-[13px] font-medium text-foreground transition-colors hover:bg-panel-2"
                >
                  {doc.label}
                  <ExternalLink className="h-3.5 w-3.5 text-ink-3" aria-hidden />
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              </li>
            ))}
          </ul>
        </SettingsSection>

        {isAdmin && <DangerZoneCard />}
      </div>
    </div>
  );
}
