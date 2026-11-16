import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectedAgentKey, useSelectedAgent, WorkspaceAgentsProvider } from "../workspaceAgents";

const mocks = vi.hoisted(() => ({
  pathname: "/overview",
  summary: vi.fn(),
}));

vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("@/client/sdk.gen", () => ({ getWorkflowsSummaryApiV1WorkflowSummaryGet: mocks.summary }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ orgContext: { organization_id: 3 } }) }));
vi.mock("@/context/AgentShellContext", () => ({
  useAgentShellOptional: () => (mocks.pathname.startsWith("/workflow/99") ? { workflowId: 99, agent: { name: "Old menu" } } : null),
}));

const AGENTS = [
  { id: 14, name: "Front desk", phone_numbers: [] },
  { id: 15, name: "Takeaway", phone_numbers: ["+35315557000"] },
];

let pick: (id: number) => void = () => {};

function Probe() {
  const { selected, select } = useSelectedAgent();
  pick = select;
  return <p data-testid="selected">{selected ? `${selected.id} ${selected.name}` : "none"}</p>;
}

function renderProvider() {
  return render(
    <WorkspaceAgentsProvider>
      <Probe />
    </WorkspaceAgentsProvider>,
  );
}

describe("the selected agent", () => {
  beforeEach(() => {
    mocks.pathname = "/overview";
    mocks.summary.mockReset();
    mocks.summary.mockResolvedValue({ data: AGENTS });
    localStorage.clear();
  });

  it("asks for the agents with the numbers that ring them", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("selected").textContent).not.toBe("none"));
    expect(mocks.summary).toHaveBeenCalledWith({ query: { status: "active", include_numbers: true } });
  });

  it("falls back to the agent a number rings", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("selected").textContent).toBe("15 Takeaway"));
  });

  it("remembers the pick per workspace", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("selected").textContent).toBe("15 Takeaway"));
    act(() => pick(14));
    expect(screen.getByTestId("selected").textContent).toBe("14 Front desk");
    expect(localStorage.getItem(selectedAgentKey(3))).toBe("14");
  });

  it("selects the agent whose screen is open", async () => {
    localStorage.setItem(selectedAgentKey(3), "15");
    mocks.pathname = "/workflow/14/settings";
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("selected").textContent).toBe("14 Front desk"));
    expect(localStorage.getItem(selectedAgentKey(3))).toBe("14");
  });

  it("stays on an agent that isn't in the live list (archived)", async () => {
    mocks.pathname = "/workflow/99/facts";
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("selected").textContent).toBe("99 Old menu"));
  });

  it("ignores a remembered agent that no longer exists", async () => {
    localStorage.setItem(selectedAgentKey(3), "404");
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("selected").textContent).toBe("15 Takeaway"));
  });
});
