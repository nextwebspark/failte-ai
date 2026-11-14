import { describe, expect, it } from "vitest";

import { AGENT_PAGES, agentHref, agentIdFromPath, agentSectionFor, isAgentCallsRoute, isAgentRoute } from "../agentNav";

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

  it("lists what the agent knows and its number first, the builder screens under Advanced", () => {
    const menu = AGENT_PAGES.filter((page) => !page.notInMenu);
    expect(menu.filter((page) => !page.advanced).map((page) => page.title)).toEqual([
      "What your agent knows",
      "Phone number",
    ]);
    expect(menu.filter((page) => page.advanced).map((page) => page.title)).toEqual([
      "Conversation",
      "Model and voice",
      "Advanced settings",
    ]);
    // An agent's calls are the main Calls row's, not a row of their own.
    expect(AGENT_PAGES.find((page) => page.segment === "/runs")?.notInMenu).toBe(true);
  });

  it("resolves each declared section", () => {
    expect(agentSectionFor("/workflow/12/facts")?.title).toBe("What your agent knows");
    expect(agentSectionFor("/workflow/12/model")?.title).toBe("Model and voice");
    expect(agentSectionFor("/workflow/12/settings")?.title).toBe("Advanced settings");
    expect(agentSectionFor("/workflow/12/deployment")?.title).toBe("Phone number");
    expect(agentSectionFor("/workflow/12/runs")?.title).toBe("Calls");
  });

  it("keeps a single call's detail page under Calls", () => {
    expect(agentSectionFor("/workflow/12/run/99")?.title).toBe("Calls");
    expect(isAgentCallsRoute("/workflow/12/run/99")).toBe(true);
    expect(isAgentCallsRoute("/workflow/12/runs")).toBe(true);
    expect(isAgentCallsRoute("/workflow/12/facts")).toBe(false);
  });

  it("is null off an agent route", () => {
    expect(agentSectionFor("/workflow")).toBeNull();
  });
});

describe("agentHref", () => {
  it("builds section links off the agent id", () => {
    expect(agentHref(12, "")).toBe("/workflow/12");
    expect(agentHref(12, "/settings")).toBe("/workflow/12/settings");
    expect(agentHref(12, "/deployment", "#phone")).toBe("/workflow/12/deployment#phone");
  });

  it("has no duplicate segments", () => {
    const segments = AGENT_PAGES.map((page) => page.segment);
    expect(new Set(segments).size).toBe(segments.length);
  });

  it("keeps the editing screens to people who may change the agent", () => {
    expect(AGENT_PAGES.find((page) => page.segment === "/model")?.requires).toBe("agents:write");
    expect(AGENT_PAGES.find((page) => page.segment === "/settings")?.requires).toBe("agents:write");
  });
});
