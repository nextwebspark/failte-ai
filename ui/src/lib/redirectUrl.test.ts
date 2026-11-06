import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ authUser: vi.fn(), count: vi.fn() }));

vi.mock("@/client/sdk.gen", () => ({
  getAuthUserApiV1UserAuthUserGet: mocks.authUser,
  getWorkflowCountApiV1WorkflowCountGet: mocks.count,
  impersonateApiV1SuperuserImpersonatePost: vi.fn(),
}));

import { getRedirectUrl } from "./utils";

describe("getRedirectUrl (Stack sign-in landing)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "log").mockImplementation(() => {});
    mocks.authUser.mockResolvedValue({ data: { id: 1, is_superuser: false } });
    mocks.count.mockResolvedValue({ data: { total: 2, active: 1 } });
  });

  it("lands an admin with live agents on their calls", async () => {
    expect(await getRedirectUrl("tok", [{ id: "admin" }])).toBe("/usage");
  });

  it("starts an admin with no live agent on creating one", async () => {
    mocks.count.mockResolvedValue({ data: { total: 1, active: 0 } });
    expect(await getRedirectUrl("tok", [{ id: "admin" }])).toBe("/workflow/create");
  });

  it("lands a member without admin on their calls", async () => {
    expect(await getRedirectUrl("tok", [])).toBe("/usage");
    expect(mocks.count).not.toHaveBeenCalled();
  });

  it("keeps superusers on the superadmin console", async () => {
    mocks.authUser.mockResolvedValue({ data: { id: 1, is_superuser: true } });
    expect(await getRedirectUrl("tok", [{ id: "admin" }])).toBe("/superadmin");
  });
});
