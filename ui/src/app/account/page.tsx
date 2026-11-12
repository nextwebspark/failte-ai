"use client";

import { UserRound } from "lucide-react";
import Link from "next/link";

import { YourAccountCard } from "@/components/privacy/YourAccountCard";
import { SettingRow, SettingsSection } from "@/components/settings/SettingsLayout";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { workspaceDisplayName } from "@/lib/workspaceName";

function profileOf(user: unknown): { name: string; email: string } {
  const u = user as {
    displayName?: string | null;
    primaryEmail?: string | null;
    email?: string | null;
  } | null;
  return { name: u?.displayName || "", email: u?.primaryEmail || u?.email || "" };
}

/**
 * Account > Your account, open to every member: who you are signed in as and
 * in which workspace, then exporting or deleting your own data. The
 * workspace's export and deletion is under Privacy & compliance.
 */
export default function AccountPage() {
  const { user, provider } = useAuth();
  const { role, orgContext } = useOrgConfig();
  const { name, email } = profileOf(user);
  const initials = (name || email || "?")
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <div className="page-body">
      <div className="flex w-full flex-col gap-[18px]">
        <SettingsSection
          id="profile"
          icon={UserRound}
          tone="brand"
          title="Profile"
          description="The account you are signed in with."
          action={
            provider === "stack" ? (
              <Link
                href="/handler/account-settings"
                className="text-caption font-medium text-brand hover:underline"
              >
                Sign-in and security
              </Link>
            ) : undefined
          }
        >
          <div className="flex items-center gap-3 px-[18px] py-4">
            <span
              aria-hidden
              className="grid size-10 shrink-0 place-items-center rounded-full border border-line bg-brand-dim font-mono text-caption font-semibold text-brand"
            >
              {initials}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[15px] font-semibold text-foreground">{name || email || "Signed in"}</p>
              {name && email && <p className="truncate text-caption text-ink-2">{email}</p>}
            </div>
          </div>
          <SettingRow label="Email" compact>
            <span className="text-caption text-foreground">{email || "—"}</span>
          </SettingRow>
          <SettingRow label="Workspace" compact>
            <span className="text-caption text-foreground">{workspaceDisplayName(orgContext?.organization_name)}</span>
          </SettingRow>
          <SettingRow label="Role" hint="Set by an admin on Members." compact>
            <span className="text-caption text-foreground">{role ? ROLE_LABELS[role] : "—"}</span>
          </SettingRow>
        </SettingsSection>

        <YourAccountCard />
      </div>
    </div>
  );
}
