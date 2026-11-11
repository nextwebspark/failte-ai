import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MemberResponse } from "@/client/types.gen";

import { MembersCard } from "../MembersCard";

vi.mock("@/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "UTC",
}));
const grant = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
  updateBookingsAccessApiV1OrganizationsMembersUserIdBookingsAccessPut: grant,
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

    expect(screen.getByText("Owner")).toBeTruthy();
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

  it("lets the owner allow a staff member to manage bookings", async () => {
    grant.mockResolvedValue({ data: undefined });
    const onChanged = vi.fn();
    const staff: MemberResponse = {
      user_id: 3,
      email: "sam@example.com",
      name: "Sam",
      role: "staff",
      joined_at: null,
      is_current_user: false,
      can_manage_bookings: false,
    };
    render(<MembersCard members={[...members, staff]} canManage={false} canGrantBookings onChanged={onChanged} />);

    expect(screen.getByText("Staff")).toBeTruthy();
    // Only the staff row has the switch.
    const toggle = screen.getByRole("switch", { name: "Can manage bookings" });
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(grant).toHaveBeenCalledWith({ path: { user_id: 3 }, body: { can_manage_bookings: true } }),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows staff their access but no switch for others to flip", () => {
    const staff: MemberResponse = {
      user_id: 3,
      email: "sam@example.com",
      name: "Sam",
      role: "staff",
      joined_at: null,
      is_current_user: false,
      can_manage_bookings: true,
    };
    render(<MembersCard members={[staff]} canManage={false} onChanged={vi.fn()} />);
    const toggle = screen.getByRole("switch", { name: "Can manage bookings" });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(toggle.hasAttribute("disabled")).toBe(true);
  });
});
