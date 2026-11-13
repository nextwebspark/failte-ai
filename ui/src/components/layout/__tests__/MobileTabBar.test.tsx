import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hidesTabBar, MobileTabBar } from "../MobileTabBar";

const mocks = vi.hoisted(() => ({
  pathname: "/overview",
  logout: vi.fn(),
  setTheme: vi.fn(),
  openHelp: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureFlags: () => ({}) }));
vi.mock("@/context/TelephonyConfigWarningsContext", () => ({
  useTelephonyConfigWarnings: () => ({
    telnyxMissingWebhookPublicKeyCount: 0,
    vonageMissingSignatureSecretCount: 0,
  }),
}));
vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => ({ role: "viewer", can: () => true, orgContext: { organization_name: "Trattoria Bella" } }),
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { displayName: "Maria Keane" }, logout: mocks.logout }),
}));
vi.mock("@/components/dashboard/useDashboardData", () => ({ useOpenFollowUpCount: () => null }));
vi.mock("../workspaceAgents", () => {
  const agents = [{ id: 14, name: "Bia", phone_numbers: ["+35315557000"] }];
  return {
    useWorkspaceAgents: () => agents,
    useSelectedAgent: () => ({ agents, selected: agents[0], select: () => {} }),
  };
});
vi.mock("@/components/help/HelpPanel", () => ({ useHelpPanel: () => ({ openHelp: mocks.openHelp }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: mocks.setTheme }) }));

describe("MobileTabBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.pathname = "/overview";
  });

  it("has Home, Calls, Follow-ups, Your agent and More, with the current one marked", () => {
    render(<MobileTabBar />);
    const bar = screen.getByRole("navigation", { name: "Main" });
    const names = within(bar)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(names).toEqual(["Home", "Calls", "Follow-ups", "Your agent"]);
    expect(within(bar).getByRole("button", { name: "More" })).toBeTruthy();
    expect(within(bar).getByRole("link", { name: "Home" }).getAttribute("aria-current")).toBe("page");
    expect(within(bar).getByRole("link", { name: "Your agent" }).getAttribute("href")).toBe("/workflow/14/facts");
  });

  it("lights Your agent on any of the agent's screens, and Calls on its calls", () => {
    mocks.pathname = "/workflow/14/deployment";
    const { unmount } = render(<MobileTabBar />);
    expect(screen.getByRole("link", { name: "Your agent" }).getAttribute("aria-current")).toBe("page");
    unmount();

    mocks.pathname = "/workflow/14/runs";
    render(<MobileTabBar />);
    expect(screen.getByRole("link", { name: "Calls" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Your agent" }).getAttribute("aria-current")).toBeNull();
  });

  it("opens More as a sheet with everything else, and closes it on Escape", async () => {
    render(<MobileTabBar />);
    const more = screen.getByRole("button", { name: "More" });
    fireEvent.click(more);
    const sheet = await screen.findByRole("dialog");
    for (const name of ["Bookings", "Reports", "Phone number", "Voice agents", "Team", "Billing", "Settings"]) {
      expect(within(sheet).getByRole("link", { name: new RegExp(name) })).toBeTruthy();
    }
    // The agent the Agent rows open, and the number that rings it.
    expect(within(sheet).getByTestId("agent-switcher").textContent).toContain("Bia");
    expect(within(sheet).getByRole("button", { name: /Help/ })).toBeTruthy();
    expect(within(sheet).getByText("Trattoria Bella")).toBeTruthy();
    expect(within(sheet).getByText("Maria Keane · Owner")).toBeTruthy();
    const advanced = within(sheet).getByRole("button", { name: /Advanced setup/ });
    expect(advanced.textContent).toContain("Best on a computer");
    fireEvent.click(advanced);
    expect(within(sheet).getByRole("link", { name: "Telephony" })).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: /^Advanced(?! setup)/ }));
    expect(within(sheet).getByRole("link", { name: "Model and voice" }).getAttribute("href")).toBe("/workflow/14/model");

    fireEvent.keyDown(sheet, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens the Help panel from the sheet", async () => {
    render(<MobileTabBar />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(await screen.findByRole("button", { name: /Help/ }));
    expect(mocks.openHelp).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("signs out from the sheet", async () => {
    render(<MobileTabBar />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(mocks.logout).toHaveBeenCalled();
  });

  it("closes the sheet when the screen changes", async () => {
    const { rerender } = render(<MobileTabBar />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    await screen.findByRole("dialog");
    mocks.pathname = "/bookings";
    rerender(<MobileTabBar />);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("stays off the full-screen conversation diagram only", () => {
    expect(hidesTabBar("/workflow/14")).toBe(true);
    expect(hidesTabBar("/workflow/14/facts")).toBe(false);
    expect(hidesTabBar("/workflow")).toBe(false);
  });
});
