import { describe, expect, it } from "vitest";

import {
  AGENT_NAV_SECTIONS,
  agentHref,
  agentIdFromPath,
  agentSectionFor,
  isAgentRoute,
} from "../agentNav";

describe("agentIdFromPath", () => {
  it("reads the id off every agent-level screen", () => {
    expect(agentIdFromPath("/workflow/12")).toBe(12);
    expect(agentIdFromPath("/workflow/12/settings")).toBe(12);
    expect(agentIdFromPath("/workflow/12/run/99")).toBe(12);
  });

  it("is null for the workspace list and the create screen", () => {
    expect(agentIdFromPath("/workflow")).toBeNull();
    expect(agentIdFromPath("/workflow/create")).toBeNull();
    expect(agentIdFromPath("/campaigns/12")).toBeNull();
    expect(isAgentRoute("/workflow/create")).toBe(false);
    expect(isAgentRoute("/workflow/12")).toBe(true);
  });
});

describe("agentSectionFor", () => {
  it("treats the bare agent route as the conversation", () => {
    expect(agentSectionFor("/workflow/12")?.title).toBe("Conversation");
  });

  it("resolves each declared section", () => {
    expect(agentSectionFor("/workflow/12/model")?.title).toBe("Model and voice");
    expect(agentSectionFor("/workflow/12/settings")?.title).toBe("Advanced settings");
    expect(agentSectionFor("/workflow/12/deployment")?.title).toBe("Deployment");
    expect(agentSectionFor("/workflow/12/runs")?.title).toBe("Runs");
  });

  it("keeps a single run's detail page under Runs", () => {
    expect(agentSectionFor("/workflow/12/run/99")?.title).toBe("Runs");
  });

  it("is null off an agent route", () => {
    expect(agentSectionFor("/workflow")).toBeNull();
  });
});

describe("agentHref", () => {
  it("builds section links off the agent id", () => {
    expect(agentHref(12, "")).toBe("/workflow/12");
    expect(agentHref(12, "/settings")).toBe("/workflow/12/settings");
  });

  it("has no duplicate segments across the nav", () => {
    const segments = AGENT_NAV_SECTIONS.flatMap((section) =>
      section.items.map((item) => item.segment),
    );
    expect(new Set(segments).size).toBe(segments.length);
  });
});
