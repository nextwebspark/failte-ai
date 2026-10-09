import { afterEach, describe, expect, it } from "vitest";

import { migrateStorageKey } from "./storageKeys";

describe("migrateStorageKey", () => {
  afterEach(() => localStorage.clear());

  it("moves the legacy value to the new key", () => {
    localStorage.setItem("old", "v1");
    migrateStorageKey("old", "new");
    expect(localStorage.getItem("new")).toBe("v1");
    expect(localStorage.getItem("old")).toBeNull();
  });

  it("keeps an existing new value and drops the legacy one", () => {
    localStorage.setItem("old", "stale");
    localStorage.setItem("new", "fresh");
    migrateStorageKey("old", "new");
    expect(localStorage.getItem("new")).toBe("fresh");
    expect(localStorage.getItem("old")).toBeNull();
  });

  it("does nothing when there is no legacy value", () => {
    migrateStorageKey("old", "new");
    expect(localStorage.getItem("new")).toBeNull();
  });
});
