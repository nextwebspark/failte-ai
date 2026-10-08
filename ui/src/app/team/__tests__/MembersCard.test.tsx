import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MemberResponse } from "@/client/types.gen";

import { MembersCard } from "../MembersCard";

vi.mock("@/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "UTC",
}));
vi.mock("@/client/sdk.gen", () => ({
  leaveCurrentOrganizationApiV1OrganizationsLeavePost: vi.fn(),
  removeMemberApiV1OrganizationsMembersUserIdDelete: vi.fn(),
  updateMemberRoleApiV1OrganizationsMembersUserIdPatch: vi.fn(),
}));

const members: MemberResponse[] = [
  {
    user_id: 1,
    email: "ada@example.com",
    name: "Ada",
    role: "admin",
    joined_at: "2026-10-01T10:00:00Z",
    is_current_user: true,
  },
  {
    user_id: 2,
    email: "cli@example.com",
    name: null,
    role: "viewer",
    joined_at: "2026-10-02T10:00:00Z",
    is_current_user: false,
  },
];

describe("MembersCard", () => {
  it("shows read-only role badges and no remove buttons to non-admins", () => {
    render(<MembersCard members={members} canManage={false} onChanged={vi.fn()} />);

    expect(screen.getByText("Client")).toBeTruthy();
    expect(screen.getByText("You")).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByLabelText(/^Remove /)).toBeNull();
    // Everyone can leave.
    expect(screen.getByLabelText("Leave workspace")).toBeTruthy();
  });

  it("gives admins a role picker per member and remove for others only", () => {
    render(<MembersCard members={members} canManage onChanged={vi.fn()} />);

    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.getByLabelText("Remove cli@example.com")).toBeTruthy();
    expect(screen.queryByLabelText("Remove Ada")).toBeNull();
  });
});
