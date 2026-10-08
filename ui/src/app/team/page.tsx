"use client";

import { PageActions } from "@/components/layout/PageActionsSlot";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrgConfig } from "@/context/OrgConfigContext";

import { InvitationsCard } from "./InvitationsCard";
import { InviteDialog } from "./InviteDialog";
import { MembersCard } from "./MembersCard";
import { OrganizationNameCard } from "./OrganizationNameCard";
import { useTeam } from "./useTeam";

export default function TeamPage() {
  const { can } = useOrgConfig();
  const { members, invitations, loading, error, refresh, canManage } = useTeam();

  return (
    <div className="page-body">
      {canManage && (
        <PageActions>
          <InviteDialog onInvited={() => void refresh()} />
        </PageActions>
      )}
      <div className="w-full max-w-3xl space-y-6">
        {can("org:manage") && <OrganizationNameCard />}
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : loading ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <MembersCard members={members} canManage={canManage} onChanged={() => void refresh()} />
            {canManage && (
              <InvitationsCard invitations={invitations} onChanged={() => void refresh()} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
