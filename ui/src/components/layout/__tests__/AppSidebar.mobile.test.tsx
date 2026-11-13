import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarProvider, useSidebar } from "@/components/ui/sidebar";

import { ADVANCED_OPEN_KEY, AGENT_ADVANCED_OPEN_KEY, AppSidebar } from "../AppSidebar";

const mocks = vi.hoisted(() => ({
  pathname: "/overview",
  agents: [{ id: 14, name: "Bia Bistro bookings", phone_numbers: [] }] as
    | { id: number; name: string; phone_numbers: string[] }[]
    | null,
  role: "admin" as string | null,
  can: (() => true) as (p: string) => boolean,
  mobile: true,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mocks.mobile }));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureFlags: () => ({}) }));
vi.mock("@/context/AgentShellContext", () => ({ useAgentShellOptional: () => null }));
vi.mock("@/context/TelephonyConfigWarningsContext", () => ({
  useTelephonyConfigWarnings: () => ({
    telnyxMissingWebhookPublicKeyCount: 0,
    vonageMissingSignatureSecretCount: 0,
  }),
}));
vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => ({
    role: mocks.role,
    can: (p: string) => mocks.can(p),
    orgContext: { organization_name: "Trattoria Bella" },
  }),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { displayName: "Maria Keane" } }) }));
vi.mock("@/components/dashboard/useDashboardData", () => ({ useOpenFollowUpCount: () => null }));
vi.mock("../workspaceAgents", () => ({
  useWorkspaceAgents: () => mocks.agents,
  useSelectedAgent: () => ({ agents: mocks.agents, selected: mocks.agents?.[0] ?? null, select: vi.fn() }),
}));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));

// Radix measures some parts of the menu; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function OpenButton() {
  const { setOpenMobile, openMobile } = useSidebar();
  return (
    <button type="button" onClick={() => setOpenMobile(true)}>
      {openMobile ? "menu open" : "menu closed"}
    </button>
  );
}

function Shell() {
  return (
    <SidebarProvider>
      <OpenButton />
      <AppSidebar />
    </SidebarProvider>
  );
}

async function openMenu() {
  render(<Shell />);
  fireEvent.click(screen.getByText("menu closed"));
  await screen.findByRole("link", { name: "Home" });
}

describe("AppSidebar on a phone", () => {
  beforeEach(() => {
    mocks.pathname = "/overview";
    mocks.agents = [{ id: 14, name: "Bia Bistro bookings", phone_numbers: [] }];
    mocks.role = "admin";
    mocks.can = () => true;
    mocks.mobile = true;
    localStorage.clear();
  });

  it("closes the menu after picking a screen", async () => {
    await openMenu();
    fireEvent.click(screen.getByRole("link", { name: "Calls" }));
    await waitFor(() => expect(screen.getByText("menu closed")).toBeTruthy());
  });

  it("closes the menu when the screen changes some other way (Back, Forward)", async () => {
    const { rerender } = render(<Shell />);
    fireEvent.click(screen.getByText("menu closed"));
    await screen.findByRole("link", { name: "Home" });
    expect(screen.getByText("menu open")).toBeTruthy();

    mocks.pathname = "/files";
    rerender(<Shell />);
    await waitFor(() => expect(screen.getByText("menu closed")).toBeTruthy());
  });

  it("marks the section of a nested screen as the current page, opening Advanced setup for it", async () => {
    mocks.pathname = "/telephony-configurations/7";
    await openMenu();
    const current = await screen.findByRole("link", { current: "page" });
    expect(current.textContent).toContain("Telephony");
    expect(screen.getByRole("button", { name: "Advanced setup" }).getAttribute("aria-expanded")).toBe("true");
  });
});

describe("AppSidebar layout", () => {
  beforeEach(() => {
    mocks.pathname = "/overview";
    mocks.agents = [{ id: 14, name: "Bia Bistro bookings", phone_numbers: [] }];
    mocks.role = "admin";
    mocks.can = () => true;
    mocks.mobile = true;
    localStorage.clear();
  });

  it("lists the business first, then the agent, then the workspace, with the builder screens folded away", async () => {
    await openMenu();
    const links = screen.getAllByRole("link").map((a) => a.textContent?.trim());
    expect(links).toEqual([
      "Home",
      "Calls",
      "Follow-ups",
      "Bookings",
      "Reports",
      "What your agent knows",
      "Phone number",
      "Voice agents",
      "Team",
      "Billing",
      "Settings",
    ]);
    expect(screen.getByText("Agent")).toBeTruthy();
    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Advanced" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/for your developer/i)).toBeNull();
    expect(screen.getByRole("link", { name: "Home" }).getAttribute("aria-current")).toBe("page");
  });

  it("shows the business and the signed-in person", async () => {
    await openMenu();
    expect(screen.getByText("Trattoria Bella")).toBeTruthy();
    expect(screen.getByText("Maria Keane")).toBeTruthy();
    expect(screen.getByText("Admin")).toBeTruthy();
  });

  it("opens Advanced setup on request and remembers it", async () => {
    await openMenu();
    const toggle = screen.getByRole("button", { name: "Advanced setup" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    for (const name of ["Models & voice", "Telephony", "Tools", "Integrations", "Files", "Prompt audio"]) {
      expect(screen.getByRole("link", { name })).toBeTruthy();
    }
    expect(localStorage.getItem(ADVANCED_OPEN_KEY)).toBe("1");
  });

  it("opens the agent's Advanced on request and remembers it", async () => {
    await openMenu();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByRole("link", { name: "Conversation" }).getAttribute("href")).toBe("/workflow/14");
    expect(localStorage.getItem(AGENT_ADVANCED_OPEN_KEY)).toBe("1");
  });

  it("points the Agent rows at the agent", async () => {
    await openMenu();
    expect(screen.getByRole("link", { name: "What your agent knows" }).getAttribute("href")).toBe("/workflow/14/facts");
    expect(screen.getByRole("link", { name: "Phone number" }).getAttribute("href")).toBe("/workflow/14/deployment#phone");
  });

  it("leads to the agents list while the agents load", async () => {
    mocks.agents = null;
    await openMenu();
    expect(screen.getByRole("link", { name: "What your agent knows" }).getAttribute("href")).toBe("/workflow");
  });

  it("hides the builder screens an owner can't open", async () => {
    mocks.role = "viewer";
    const owner = new Set(["agents:read", "calls:read", "reports:read", "members:read", "billing:read", "campaigns:read", "agents:facts", "bookings:manage"]);
    mocks.can = (p) => owner.has(p);
    await openMenu();
    expect(screen.getByRole("link", { name: "Team" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Billing" })).toBeTruthy();
    // None of the builder screens is theirs, so the whole group is left out.
    expect(screen.queryByRole("button", { name: "Advanced setup" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Tools" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Telephony" })).toBeNull();
  });
});
