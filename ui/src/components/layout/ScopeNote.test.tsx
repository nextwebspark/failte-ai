import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { settingsScopeFor } from "@/components/settings/settingsNav";

import { scopeLabel, ScopeNote } from "./ScopeNote";

describe("ScopeNote", () => {
  it("says who a setting reaches", () => {
    expect(scopeLabel("workspace")).toBe("Workspace setting · same for every agent");
    expect(scopeLabel("you")).toBe("Only for you");
    expect(scopeLabel("agent", "Restaurant bookings · Linen Quay Kitchen")).toBe("Only for Linen Quay Kitchen");
    expect(scopeLabel("agent", "CH Marine")).toBe("Only for CH Marine");
    expect(scopeLabel("agent", null)).toBe("Only for this agent");
  });

  it("renders the note", () => {
    render(<ScopeNote scope="agent" agentName="CH Marine" />);
    expect(screen.getByText("Only for CH Marine")).toBeTruthy();
  });

  it("knows each settings screen's scope", () => {
    expect(settingsScopeFor("/settings/home-layout")).toBe("workspace");
    expect(settingsScopeFor("/settings/notifications")).toBe("workspace");
    expect(settingsScopeFor("/settings/compliance")).toBe("workspace");
    expect(settingsScopeFor("/api-keys")).toBe("workspace");
    expect(settingsScopeFor("/account")).toBe("you");
    expect(settingsScopeFor("/workflow/5/facts")).toBeNull();
  });
});
