import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  provider: vi.fn(),
  user: vi.fn(),
  token: vi.fn(),
  context: vi.fn(),
  count: vi.fn(),
  redirectUrl: vi.fn(),
}));

vi.mock("@/lib/auth/server", () => ({
  getServerAuthProvider: mocks.provider,
  getServerUser: mocks.user,
  getServerAccessToken: mocks.token,
}));
vi.mock("@/client/sdk.gen", () => ({
  getCurrentOrganizationContextApiV1OrganizationsContextGet: mocks.context,
  getWorkflowCountApiV1WorkflowCountGet: mocks.count,
}));
vi.mock("@/lib/utils", () => ({ getRedirectUrl: mocks.redirectUrl }));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn(), debug: vi.fn() } }));

import { GET } from "./route";

async function landing(): Promise<{ status: number; location: string | null }> {
  const res = await GET();
  return { status: res.status, location: res.headers.get("Location") };
}

describe("GET /after-sign-in", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.provider.mockResolvedValue("local");
    mocks.user.mockResolvedValue({ id: 1 });
    mocks.token.mockResolvedValue("tok");
    mocks.context.mockResolvedValue({ data: { role: "admin" } });
    mocks.count.mockResolvedValue({ data: { total: 2, active: 1 } });
  });

  it("answers with a plain relative 307, not a page", async () => {
    expect(await landing()).toEqual({ status: 307, location: "/workflow" });
  });

  it("sends a user without active agents to create one", async () => {
    mocks.count.mockResolvedValue({ data: { total: 1, active: 0 } });
    expect((await landing()).location).toBe("/workflow/create");
  });

  it("sends a viewer to call history", async () => {
    mocks.context.mockResolvedValue({ data: { role: "viewer" } });
    expect((await landing()).location).toBe("/usage");
    expect(mocks.count).not.toHaveBeenCalled();
  });

  it("falls back to /workflow/create without a token or when the API fails", async () => {
    mocks.token.mockResolvedValue(null);
    expect((await landing()).location).toBe("/workflow/create");
    mocks.token.mockResolvedValue("tok");
    mocks.context.mockRejectedValue(new Error("down"));
    expect((await landing()).location).toBe("/workflow/create");
  });

  it("uses the Stack redirect for Stack users", async () => {
    mocks.provider.mockResolvedValue("stack");
    mocks.user.mockResolvedValue({
      getAuthJson: async () => ({ accessToken: "stack-tok" }),
      listPermissions: async () => [{ id: "admin" }],
      selectedTeam: { id: "t" },
    });
    mocks.redirectUrl.mockResolvedValue("/superadmin");
    expect((await landing()).location).toBe("/superadmin");
    expect(mocks.redirectUrl).toHaveBeenCalledWith("stack-tok", [{ id: "admin" }]);
  });
});
