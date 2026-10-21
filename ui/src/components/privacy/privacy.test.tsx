import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DangerZoneCard } from "./DangerZoneCard";
import { NoOrganizationNotice } from "./NoOrganizationNotice";
import { PendingDeletionBanner } from "./PendingDeletionBanner";
import { YourAccountCard } from "./YourAccountCard";

const mocks = vi.hoisted(() => ({
  deleteMe: vi.fn(),
  exportMe: vi.fn(),
  exportOrg: vi.fn(),
  deleteOrg: vi.fn(),
  cancelDeletion: vi.fn(),
  logout: vi.fn(),
  refreshConfig: vi.fn(),
  orgConfig: {} as Record<string, unknown>,
}));

vi.mock("@/client/sdk.gen", () => ({
  deleteMyAccountApiV1UserMeDelete: mocks.deleteMe,
  exportMyDataApiV1UserMeExportGet: mocks.exportMe,
  exportOrganizationApiV1OrganizationsExportGet: mocks.exportOrg,
  deleteOrganizationApiV1OrganizationsDeletionPost: mocks.deleteOrg,
  cancelOrganizationDeletionRequestApiV1OrganizationsDeletionDelete:
    mocks.cancelDeletion,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { email: "aoife@example.test" },
    logout: mocks.logout,
    loading: false,
    provider: "local",
  }),
}));

vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => mocks.orgConfig,
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// Render dialogs inline so their contents are queryable.
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div role="dialog">{children}</div> : null,
  AlertDialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AlertDialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  AlertDialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  AlertDialogCancel: ({ children }: { children: ReactNode }) => (
    <button type="button">{children}</button>
  ),
}));

function orgConfig({
  admin = true,
  pending = false,
}: { admin?: boolean; pending?: boolean } = {}) {
  return {
    orgContext: {
      organization_id: 7,
      organization_name: "Acme Ltd",
      deletion: pending
        ? { pending: true, scheduled_for: "2026-11-20T03:47:00Z" }
        : null,
    },
    can: (...required: string[]) => admin || !required.includes("org:manage"),
    refreshConfig: mocks.refreshConfig,
  };
}

function lastDialogButton(name: string) {
  const buttons = screen.getAllByRole("button", { name });
  return buttons[buttons.length - 1];
}

beforeEach(() => {
  for (const mock of [
    mocks.deleteMe,
    mocks.exportMe,
    mocks.exportOrg,
    mocks.deleteOrg,
    mocks.cancelDeletion,
    mocks.logout,
    mocks.refreshConfig,
  ]) {
    mock.mockReset();
  }
  mocks.orgConfig = orgConfig();
});

describe("YourAccountCard", () => {
  it("deletes the account only once the email is typed, then signs out", async () => {
    mocks.deleteMe.mockResolvedValue({ data: undefined });
    render(<YourAccountCard />);

    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    const confirm = lastDialogButton("Delete my account");
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/to confirm/), {
      target: { value: "AOIFE@example.test " },
    });
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirm);

    await waitFor(() => expect(mocks.logout).toHaveBeenCalled());
    expect(mocks.deleteMe).toHaveBeenCalledWith({
      body: { confirm_email: "AOIFE@example.test " },
    });
  });

  it("offers to delete the organization when the user is its only member", async () => {
    mocks.deleteMe.mockResolvedValue({
      error: {
        detail: "You are the only member of Acme Ltd.",
        code: "sole_member_of_organization",
        organization_id: "7",
      },
    });
    render(<YourAccountCard />);

    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    fireEvent.change(screen.getByLabelText(/to confirm/), {
      target: { value: "aoife@example.test" },
    });
    fireEvent.click(lastDialogButton("Delete my account"));

    expect(await screen.findByText(/only member of Acme Ltd/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete Acme Ltd first" }));
    expect(screen.getByText("Delete Acme Ltd?")).toBeTruthy();
    expect(mocks.logout).not.toHaveBeenCalled();
  });

  it("explains the last-admin refusal without offering deletion", async () => {
    mocks.orgConfig = orgConfig({ admin: false });
    mocks.deleteMe.mockResolvedValue({
      error: {
        detail: "You are the only admin of Acme Ltd, which has other members.",
        code: "last_admin_of_organization",
        organization_id: "7",
      },
    });
    render(<YourAccountCard />);

    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    fireEvent.change(screen.getByLabelText(/to confirm/), {
      target: { value: "aoife@example.test" },
    });
    fireEvent.click(lastDialogButton("Delete my account"));

    expect(await screen.findByText(/only admin of Acme Ltd/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Manage members" }).getAttribute("href"),
    ).toBe("/team");
    expect(screen.queryByRole("button", { name: /first$/ })).toBeNull();
  });
});

describe("DangerZoneCard", () => {
  it("deletes the organization once its name is typed", async () => {
    mocks.deleteOrg.mockResolvedValue({ data: { pending: true } });
    render(<DangerZoneCard />);

    fireEvent.click(screen.getByRole("button", { name: "Delete organization" }));
    const confirm = lastDialogButton("Delete organization");
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/to confirm/), {
      target: { value: "acme ltd" },
    });
    fireEvent.click(confirm);

    await waitFor(() => expect(mocks.refreshConfig).toHaveBeenCalled());
    expect(mocks.deleteOrg).toHaveBeenCalledWith({
      body: { confirm_name: "acme ltd" },
    });
  });

  it("shows the erasure date and cancels a pending deletion", async () => {
    mocks.orgConfig = orgConfig({ pending: true });
    mocks.cancelDeletion.mockResolvedValue({ error: { detail: "nope" } });
    render(<DangerZoneCard />);

    expect(screen.getByText(/will be permanently erased on/)).toBeTruthy();
    expect(screen.getByText(/you can cancel until then/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete organization" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel deletion" }));
    await waitFor(() => expect(mocks.cancelDeletion).toHaveBeenCalled());
  });
});

describe("PendingDeletionBanner", () => {
  it("is hidden unless deletion is pending", () => {
    const { container } = render(<PendingDeletionBanner />);
    expect(container.innerHTML).toBe("");
  });

  it("tells non-admins who can cancel", () => {
    mocks.orgConfig = orgConfig({ admin: false, pending: true });
    render(<PendingDeletionBanner />);
    expect(screen.getByText(/An admin can cancel/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel deletion" })).toBeNull();
  });

  it("lets admins cancel", () => {
    mocks.orgConfig = orgConfig({ pending: true });
    render(<PendingDeletionBanner />);
    expect(screen.getByRole("button", { name: "Cancel deletion" })).toBeTruthy();
  });
});

describe("NoOrganizationNotice", () => {
  it("explains an erased organization and lets the user sign out", () => {
    render(<NoOrganizationNotice reason="erased" />);
    expect(screen.getByText("This organization has been deleted")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(mocks.logout).toHaveBeenCalled();
  });

  it("points a user without an organization to the switcher and their account", () => {
    render(<NoOrganizationNotice reason="none" />);
    expect(screen.getByText("You don't belong to an organization")).toBeTruthy();
    expect(screen.getByText(/workspace switcher/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Your account" }).getAttribute("href"),
    ).toBe("/account");
  });
});
