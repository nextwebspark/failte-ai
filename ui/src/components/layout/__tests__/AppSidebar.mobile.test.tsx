import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarProvider, useSidebar } from "@/components/ui/sidebar";

import { AppSidebar } from "../AppSidebar";

const mocks = vi.hoisted(() => ({ pathname: "/overview" }));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => true }));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureFlags: () => ({}) }));
vi.mock("@/context/AgentShellContext", () => ({ useAgentShellOptional: () => null }));
vi.mock("@/context/TelephonyConfigWarningsContext", () => ({
  useTelephonyConfigWarnings: () => ({
    telnyxMissingWebhookPublicKeyCount: 0,
    vonageMissingSignatureSecretCount: 0,
  }),
}));
vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => ({ role: "admin", can: () => true }),
}));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));

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

describe("AppSidebar on a phone", () => {
  beforeEach(() => {
    mocks.pathname = "/overview";
  });

  it("closes the menu after picking a screen", async () => {
    render(<Shell />);
    fireEvent.click(screen.getByText("menu closed"));
    const link = await screen.findByRole("link", { name: "Tools" });
    fireEvent.click(link);
    await waitFor(() => expect(screen.getByText("menu closed")).toBeTruthy());
  });

  it("closes the menu when the screen changes some other way (Back, Forward)", async () => {
    const { rerender } = render(<Shell />);
    fireEvent.click(screen.getByText("menu closed"));
    await screen.findByRole("link", { name: "Tools" });
    expect(screen.getByText("menu open")).toBeTruthy();

    mocks.pathname = "/files";
    rerender(<Shell />);
    await waitFor(() => expect(screen.getByText("menu closed")).toBeTruthy());
  });

  it("marks the section of a nested screen as the current page", async () => {
    mocks.pathname = "/telephony-configurations/7";
    render(<Shell />);
    fireEvent.click(screen.getByText("menu closed"));
    const current = await screen.findByRole("link", { current: "page" });
    expect(current.textContent).toContain("Telephony");
  });
});
