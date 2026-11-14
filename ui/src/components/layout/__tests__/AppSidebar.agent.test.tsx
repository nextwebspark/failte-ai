import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/ui/sidebar";

import { AppSidebar } from "../AppSidebar";

type Agent = { id: number; name: string; phone_numbers: string[] };

const mocks = vi.hoisted(() => ({
  pathname: "/workflow/14/runs",
  agents: [] as Agent[] | null,
  selectedId: 14 as number | null,
  select: vi.fn(),
  push: vi.fn(),
  role: "admin" as string | null,
  can: (() => true) as (p: string) => boolean,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: mocks.push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureFlags: () => ({}) }));
vi.mock("@/components/dashboard/useDashboardData", () => ({ useOpenFollowUpCount: () => null }));
vi.mock("@/context/AgentShellContext", () => ({
  useAgentShellOptional: () => ({ workflowId: 14, agent: { name: "Bia Bistro bookings", versionStatus: "live" } }),
}));
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
    orgContext: { organization_name: "Trattoria Bella", organization_id: 3 },
  }),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { displayName: "Maria Keane" } }) }));
vi.mock("../workspaceAgents", () => ({
  useWorkspaceAgents: () => mocks.agents,
  useSelectedAgent: () => ({
    agents: mocks.agents,
    selected: mocks.agents?.find((a) => a.id === mocks.selectedId) ?? mocks.agents?.[0] ?? null,
    select: mocks.select,
  }),
}));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));

// Radix measures some parts of the menu; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function renderMenu() {
  render(
    <SidebarProvider>
      <AppSidebar />
    </SidebarProvider>,
  );
}

const BIA: Agent = { id: 14, name: "Bia Bistro bookings", phone_numbers: ["+35315557000"] };
const TAKEAWAY: Agent = { id: 15, name: "Takeaway orders", phone_numbers: [] };

describe("AppSidebar on an agent's screens", () => {
  beforeEach(() => {
    mocks.pathname = "/workflow/14/facts";
    mocks.agents = [BIA];
    mocks.selectedId = 14;
    mocks.role = "admin";
    mocks.can = () => true;
    mocks.select.mockReset();
    mocks.push.mockReset();
    localStorage.clear();
  });

  it("keeps the one menu: the business rows stay, with the agent's own rows", () => {
    renderMenu();
    for (const name of ["Home", "Calls", "Follow-ups", "Voice agents", "Settings"]) {
      expect(screen.getByRole("link", { name })).toBeTruthy();
    }
    expect(screen.queryByRole("link", { name: /back to home/i })).toBeNull();
    expect(screen.getByRole("link", { name: "What your agent knows" }).getAttribute("aria-current")).toBe("page");
    // Voice agents is the list, not the agent's screens.
    expect(screen.getByRole("link", { name: "Voice agents" }).getAttribute("aria-current")).toBeNull();
  });

  it("names the agent and the number that rings it", () => {
    renderMenu();
    const switcher = screen.getByTestId("agent-switcher");
    expect(switcher.textContent).toContain("Bia Bistro bookings");
    expect(switcher.textContent).toContain("Answers +353");
  });

  it("shows people who may change the agent every screen, under Advanced", () => {
    mocks.pathname = "/workflow/14/model";
    renderMenu();
    expect(screen.getByRole("button", { name: "Advanced" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("link", { name: "Model and voice" }).getAttribute("href")).toBe("/workflow/14/model");
    expect(screen.getByRole("link", { name: "Advanced settings" }).getAttribute("href")).toBe("/workflow/14/settings");
    expect(screen.getByRole("link", { name: "Conversation" }).getAttribute("href")).toBe("/workflow/14");
  });

  it("leaves the editing screens out for staff, who can't open them", () => {
    mocks.role = "staff";
    const staff = new Set(["agents:read", "calls:read", "reports:read", "followups:manage"]);
    mocks.can = (p) => staff.has(p);
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.queryByRole("link", { name: "Model and voice" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Advanced settings" })).toBeNull();
    expect(screen.getByRole("link", { name: "Conversation" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "What your agent knows" })).toBeTruthy();
    for (const name of ["Team", "Billing", "Tools", "Telephony", "Models & voice", "Files", "Prompt audio"]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
  });

  it("lights Calls on an agent's calls", () => {
    mocks.pathname = "/workflow/14/runs";
    renderMenu();
    expect(screen.getByRole("link", { name: "Calls" }).getAttribute("aria-current")).toBe("page");
  });

  it("points every agent row at the agent picked, and opens the same screen for another agent", async () => {
    mocks.agents = [BIA, TAKEAWAY];
    mocks.pathname = "/workflow/14/facts";
    renderMenu();
    expect(screen.getByRole("link", { name: "Phone number" }).getAttribute("href")).toBe("/workflow/14/deployment#phone");

    fireEvent.pointerDown(screen.getByRole("button", { name: /Agent: Bia Bistro bookings/ }), { button: 0, ctrlKey: false });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("No phone number yet")).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: /Create agent/ })).toBeTruthy();
    fireEvent.click(within(menu).getByRole("menuitem", { name: /Takeaway orders/ }));
    expect(mocks.select).toHaveBeenCalledWith(15);
    expect(mocks.push).toHaveBeenCalledWith("/workflow/15/facts");
  });

  it("only picks the agent off an agent's screen, without leaving the page", async () => {
    mocks.agents = [BIA, TAKEAWAY];
    mocks.pathname = "/overview";
    renderMenu();
    fireEvent.pointerDown(screen.getByRole("button", { name: /Agent: Bia Bistro bookings/ }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: /Takeaway orders/ }));
    expect(mocks.select).toHaveBeenCalledWith(15);
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("has no picker with one agent", () => {
    renderMenu();
    expect(screen.queryByRole("button", { name: /Agent:/ })).toBeNull();
  });

  it("offers to create the first agent instead of agent rows", () => {
    mocks.agents = [];
    mocks.selectedId = null;
    mocks.pathname = "/overview";
    renderMenu();
    expect(screen.getByRole("link", { name: "Create your agent" }).getAttribute("href")).toBe("/workflow/create");
    expect(screen.queryByRole("link", { name: "What your agent knows" })).toBeNull();
  });
});
