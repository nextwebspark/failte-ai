"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  listInvitationsApiV1OrganizationsInvitationsGet,
  listMembersApiV1OrganizationsMembersGet,
} from "@/client/sdk.gen";
import type { InvitationResponse, MemberResponse } from "@/client/types.gen";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

/** Members (everyone) and open invitations (admins only) of the current org. */
export function useTeam() {
  const { user, loading: authLoading } = useAuth();
  const { can, role } = useOrgConfig();
  const canManage = can("members:manage");
  const [members, setMembers] = useState<MemberResponse[]>([]);
  const [invitations, setInvitations] = useState<InvitationResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const hasFetched = useRef(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [membersRes, invitationsRes] = await Promise.all([
      listMembersApiV1OrganizationsMembersGet(),
      canManage ? listInvitationsApiV1OrganizationsInvitationsGet() : Promise.resolve(null),
    ]);
    if (membersRes.error) {
      setError(detailFromError(membersRes.error, "Failed to load members"));
    } else {
      setMembers(membersRes.data ?? []);
      setError(null);
    }
    if (invitationsRes && !invitationsRes.error) {
      setInvitations(invitationsRes.data ?? []);
    }
    setLoading(false);
  }, [canManage]);

  useEffect(() => {
    // Wait for auth and for the role, which decides what to fetch.
    if (authLoading || !user || role === null || hasFetched.current) return;
    hasFetched.current = true;
    void refresh();
  }, [authLoading, user, role, refresh]);

  return { members, invitations, loading, error, refresh, canManage };
}
