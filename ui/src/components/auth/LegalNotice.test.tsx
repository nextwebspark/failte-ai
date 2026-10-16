import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LegalNotice } from "./LegalNotice";

describe("LegalNotice", () => {
  it("links our own terms and privacy policy in a new tab", () => {
    render(<LegalNotice />);
    const terms = screen.getByRole("link", { name: /Terms of Service/ });
    const privacy = screen.getByRole("link", { name: /Privacy Policy/ });
    expect(terms.getAttribute("href")).toBe("https://lightmove.ai/terms");
    expect(privacy.getAttribute("href")).toBe("https://lightmove.ai/privacy");
    for (const link of [terms, privacy]) {
      expect(link.getAttribute("target")).toBe("_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
    }
  });
});
