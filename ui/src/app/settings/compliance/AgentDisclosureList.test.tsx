import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentDisclosureList } from "./AgentDisclosureList";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
}));

vi.mock("@/client/sdk.gen", () => ({
  getWorkflowsApiV1WorkflowFetchGet: mocks.list,
  getWorkflowApiV1WorkflowFetchWorkflowIdGet: mocks.get,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: 1 }, loading: false }),
}));

const details: Record<number, unknown> = {
  1: { id: 1, name: "Reception", workflow_configurations: null },
  2: {
    id: 2,
    name: "Bookings",
    workflow_configurations: { call_disclosure: { enabled: false } },
  },
  3: {
    id: 3,
    name: "Out of hours",
    workflow_configurations: { call_disclosure: { enabled: true, type: "audio", recording_id: "r1" } },
  },
};

describe("AgentDisclosureList", () => {
  beforeEach(() => {
    mocks.list.mockReset();
    mocks.get.mockReset();
    mocks.list.mockResolvedValue({
      data: [1, 2, 3].map((id) => ({ id, name: `agent ${id}`, status: "active" })),
    });
    mocks.get.mockImplementation(async ({ path }: { path: { workflow_id: number } }) => ({
      data: details[path.workflow_id],
    }));
  });

  it("reports each active agent's notice, treating a never-saved setting as on", async () => {
    render(<AgentDisclosureList />);

    expect(await screen.findByText("1 of 3 active agents do not play the notice. Turn it back on unless callers are told another way.")).toBeTruthy();
    expect(mocks.list).toHaveBeenCalledWith({ query: { status: "active" } });
    expect(screen.getAllByText("On")).toHaveLength(2);
    expect(screen.getByText("Off")).toBeTruthy();
    expect(screen.getByText("Plays a recorded notice")).toBeTruthy();
    expect(screen.getByText("No notice at the start of calls")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Edit notice for Bookings" }).getAttribute("href"),
    ).toBe("/workflow/2/settings#call");
  });

  it("says so when an agent's settings could not be read, instead of guessing", async () => {
    mocks.get.mockImplementation(async ({ path }: { path: { workflow_id: number } }) =>
      path.workflow_id === 2 ? { error: { detail: "boom" } } : { data: details[path.workflow_id] },
    );
    render(<AgentDisclosureList />);

    expect((await screen.findByRole("alert")).textContent).toContain("Could not read every agent's settings");
    expect(screen.queryByText("On")).toBeNull();
  });
});
