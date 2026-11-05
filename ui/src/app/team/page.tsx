"use client";

import { PageActions } from "@/components/layout/PageActionsSlot";
import { Skeleton } from "@/components/ui/skeleton";
import { useOrgConfig } from "@/context/OrgConfigContext";

import { InvitationsCard } from "./InvitationsCard";
import { InviteDialog } from "./InviteDialog";
import { MembersCard } from "./MembersCard";
import { useTeam } from "./useTeam";

export default function TeamPage() {
  const { members, invitations, loading, error, refresh, canManage } = useTeam();
  const { can } = useOrgConfig();

  return (
    <div className="page-body">
      {canManage && (
        <PageActions>
          <InviteDialog onInvited={() => void refresh()} />
        </PageActions>
      )}
      <div className="w-full space-y-6">
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : loading ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <MembersCard
              members={members}
              canManage={canManage}
              canGrantBookings={can("bookings:grant")}
              onChanged={() => void refresh()}
            />
            {canManage && (
              <InvitationsCard invitations={invitations} onChanged={() => void refresh()} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
