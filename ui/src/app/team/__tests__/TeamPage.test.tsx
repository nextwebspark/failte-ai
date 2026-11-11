import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TeamPage from "../page";

const mocks = vi.hoisted(() => ({
  members: vi.fn(),
  invitations: vi.fn(),
  updateRole: vi.fn(),
  perms: [] as string[],
  auth: { user: { id: "u1" }, loading: false },
}));

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
// Radix Select measures and scrolls; jsdom has neither.
Element.prototype.scrollIntoView = vi.fn();
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();

vi.mock("@/client/sdk.gen", () => ({
  listMembersApiV1OrganizationsMembersGet: mocks.members,
  listInvitationsApiV1OrganizationsInvitationsGet: mocks.invitations,
  updateMemberRoleApiV1OrganizationsMembersUserIdPatch: mocks.updateRole,
  updateBookingsAccessApiV1OrganizationsMembersUserIdBookingsAccessPut: vi.fn(),
  leaveCurrentOrganizationApiV1OrganizationsLeavePost: vi.fn(),
  removeMemberApiV1OrganizationsMembersUserIdDelete: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => ({
    role: "admin",
    can: (...required: string[]) => required.every((p) => mocks.perms.includes(p)),
  }),
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({ useOrganizationTimezone: () => "UTC" }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/layout/PageActionsSlot", () => ({
  PageActions: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock("../InviteDialog", () => ({ InviteDialog: () => <button type="button">Invite</button> }));
vi.mock("../InvitationsCard", () => ({ InvitationsCard: () => <div>Invitations</div> }));

const MEMBERS = [
  { user_id: 1, email: "ada@example.com", name: "Ada", role: "admin", joined_at: null, is_current_user: true },
  { user_id: 2, email: "cli@example.com", name: "Cliodhna", role: "staff", joined_at: null, is_current_user: false },
];

describe("TeamPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.perms = ["members:read", "members:manage"];
    mocks.members.mockResolvedValue({ data: MEMBERS });
    mocks.invitations.mockResolvedValue({ data: [] });
    mocks.updateRole.mockResolvedValue({ data: {} });
  });

  it("lists the members, with invites for admins", async () => {
    render(<TeamPage />);
    expect(await screen.findByText("Cliodhna")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Invite" })).toBeTruthy();
    expect(screen.getByText("Invitations")).toBeTruthy();
  });

  it("names each role picker after its member", async () => {
    render(<TeamPage />);
    await screen.findByText("Cliodhna");
    expect(screen.getByRole("combobox", { name: "Role for Ada" })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Role for Cliodhna" })).toBeTruthy();
  });

  it("hides invites and role pickers from people who can only see the team", async () => {
    mocks.perms = ["members:read"];
    render(<TeamPage />);
    await screen.findByText("Cliodhna");
    expect(screen.queryByRole("button", { name: "Invite" })).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(mocks.invitations).not.toHaveBeenCalled();
  });

  it("shows a load error with Try again, then recovers", async () => {
    mocks.members.mockResolvedValueOnce({ error: { detail: "Members are unavailable" } });
    render(<TeamPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Members are unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Cliodhna")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("handles a network failure while loading", async () => {
    mocks.members.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<TeamPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load your team. Please try again.");
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
  });

  async function pickRole(member: string, label: string) {
    const trigger = await screen.findByRole("combobox", { name: `Role for ${member}` });
    fireEvent.keyDown(trigger, { key: "Enter" });
    const option = await screen.findByRole("option", { name: new RegExp(`^${label}`) });
    fireEvent.click(option);
  }

  it("changes a member's role", async () => {
    render(<TeamPage />);
    await pickRole("Cliodhna", "Owner");
    await waitFor(() =>
      expect(mocks.updateRole).toHaveBeenCalledWith({ path: { user_id: 2 }, body: { role: "viewer" } }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Cliodhna is now an owner"));
  });

  it("tells the admin when the role change is refused", async () => {
    mocks.updateRole.mockResolvedValue({ error: { detail: "A workspace needs at least one admin." } });
    render(<TeamPage />);
    await pickRole("Cliodhna", "Owner");
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("A workspace needs at least one admin."));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("tells the admin when the network fails during a role change, and frees the picker", async () => {
    mocks.updateRole.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<TeamPage />);
    await pickRole("Cliodhna", "Owner");
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Couldn't change the role. Check your connection and try again."),
    );
    expect(screen.getByRole("combobox", { name: "Role for Cliodhna" }).hasAttribute("disabled")).toBe(false);
  });
});
