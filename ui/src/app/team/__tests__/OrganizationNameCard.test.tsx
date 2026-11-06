import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationNameCard } from "../OrganizationNameCard";

const mocks = vi.hoisted(() => ({
  orgContext: null as { organization_name: string | null } | null,
  rename: vi.fn(),
  refreshConfig: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/client/sdk.gen", () => ({
  renameCurrentOrganizationApiV1OrganizationsCurrentPatch: mocks.rename,
}));
vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => ({ orgContext: mocks.orgContext, refreshConfig: mocks.refreshConfig }),
}));

const box = () => screen.getByLabelText("Workspace name") as HTMLInputElement;

describe("OrganizationNameCard", () => {
  beforeEach(() => {
    mocks.orgContext = null;
    mocks.rename.mockReset();
  });

  it("prefills the saved name once the workspace has loaded", () => {
    const { rerender } = render(<OrganizationNameCard />);
    expect(box().value).toBe("");

    mocks.orgContext = { organization_name: "Murphy's Bistro" };
    rerender(<OrganizationNameCard />);
    expect(box().value).toBe("Murphy's Bistro");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the name the header shows when the workspace was never named", () => {
    mocks.orgContext = { organization_name: null };
    render(<OrganizationNameCard />);
    expect(box().value).toBe("My workspace");
  });

  it("keeps what the owner typed and saves it", async () => {
    mocks.orgContext = { organization_name: "My workspace" };
    mocks.rename.mockResolvedValue({ data: {} });
    render(<OrganizationNameCard />);

    fireEvent.change(box(), { target: { value: "Glen Dental" } });
    expect(box().value).toBe("Glen Dental");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mocks.rename).toHaveBeenCalledWith({ body: { name: "Glen Dental" } }),
    );
  });
});
