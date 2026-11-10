import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/ui/sidebar";

import { AppSidebar } from "../AppSidebar";

const mocks = vi.hoisted(() => ({
  pathname: "/workflow/14/runs",
  agents: [{ id: 14, name: "Bia Bistro bookings" }] as { id: number; name: string }[] | null,
  role: "admin" as string | null,
  can: (() => true) as (p: string) => boolean,
  mobile: false,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mocks.mobile }));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureFlags: () => ({}) }));
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
    orgContext: { organization_name: "Trattoria Bella" },
  }),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { displayName: "Maria Keane" } }) }));
vi.mock("../workspaceAgents", () => ({ useWorkspaceAgents: () => mocks.agents }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));

// Radix measures some parts of the menu; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function renderAgentMenu() {
  render(
    <SidebarProvider>
      <AppSidebar />
    </SidebarProvider>,
  );
}

describe("AppSidebar on an agent's screens", () => {
  it("shows people who may change the agent every screen", () => {
    mocks.can = () => true;
    renderAgentMenu();
    expect(screen.getByRole("link", { name: "Model and voice" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Advanced settings" })).toBeTruthy();
  });

  it("leaves the editing screens out for staff, who can't open them", () => {
    mocks.can = (p) => p !== "agents:write";
    renderAgentMenu();
    expect(screen.queryByRole("link", { name: "Model and voice" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Advanced settings" })).toBeNull();
    expect(screen.getByRole("link", { name: "Calls" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "What your agent knows" })).toBeTruthy();
  });
});
