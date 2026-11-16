import { describe, expect, it } from "vitest";

import { arrangeCards, hideCard, pinCard, unhideCard, unpinCard } from "./homeLayout";

const PRESENT = ["tiles", "attention", "recent-calls", "your-agent"] as const;

describe("Home layout", () => {
  it("leaves out hidden cards and counts them", () => {
    const out = arrangeCards({ hidden: ["tiles", "quick-links"], pinned: [] }, PRESENT, false);
    expect(out.rest).toEqual(["attention", "recent-calls", "your-agent"]);
    // Only cards this Home has are counted.
    expect(out.hiddenCount).toBe(1);
  });

  it("brings hidden cards back in their usual place with Show hidden", () => {
    const out = arrangeCards({ hidden: ["attention"], pinned: [] }, PRESENT, true);
    expect(out.rest).toEqual(["tiles", "attention", "recent-calls", "your-agent"]);
  });

  it("puts pinned cards first in pin order, ignoring cards this Home doesn't have", () => {
    const out = arrangeCards({ hidden: [], pinned: ["your-agent", "get-started", "tiles"] }, PRESENT, false);
    expect(out.pinned).toEqual(["your-agent", "tiles"]);
    expect(out.rest).toEqual(["attention", "recent-calls"]);
  });

  it("shows a card it doesn't know about", () => {
    const out = arrangeCards({ hidden: ["something-new"], pinned: [] }, PRESENT, false);
    expect(out.rest).toEqual([...PRESENT]);
  });

  it("unpins a card it hides, and shows a card it pins", () => {
    expect(hideCard({ hidden: [], pinned: ["tiles"] }, "tiles")).toEqual({ hidden: ["tiles"], pinned: [] });
    expect(pinCard({ hidden: ["tiles"], pinned: ["attention"] }, "tiles")).toEqual({
      hidden: [],
      pinned: ["attention", "tiles"],
    });
    expect(unhideCard({ hidden: ["tiles", "attention"], pinned: [] }, "tiles")).toEqual({ hidden: ["attention"], pinned: [] });
    expect(unpinCard({ hidden: [], pinned: ["tiles", "attention"] }, "tiles")).toEqual({ hidden: [], pinned: ["attention"] });
  });
});
