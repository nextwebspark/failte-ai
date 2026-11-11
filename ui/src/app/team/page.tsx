"use client";

import { PageActions } from "@/components/layout/PageActionsSlot";
import { Button } from "@/components/ui/button";
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
        {error && !loading ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4"
          >
            <p className="text-sm text-destructive">{error}</p>
            <Button size="sm" variant="outline" onClick={() => void refresh()}>
              Try again
            </Button>
          </div>
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
