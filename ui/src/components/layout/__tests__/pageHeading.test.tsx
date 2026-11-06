import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "@/components/ui/page-header";

import { PageHeadingProvider, usePageHeadingOwned } from "../pageHeading";

/** Stands in for the app header: an h1 unless the page has its own. */
function FakeTopBar() {
  const owned = usePageHeadingOwned();
  const Tag = owned ? "p" : "h1";
  return <Tag>Tools</Tag>;
}

describe("page heading hand-off", () => {
  it("leaves the header's h1 alone on a screen without its own title", () => {
    render(
      <PageHeadingProvider>
        <FakeTopBar />
        <p>content</p>
      </PageHeadingProvider>,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("gives the h1 to a screen's PageHeader, and back when it goes", () => {
    const { rerender } = render(
      <PageHeadingProvider>
        <FakeTopBar />
        <PageHeader title="Tools" description="What your agents can do on a call." />
      </PageHeadingProvider>,
    );
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0].closest("header")).not.toBeNull();
    expect(screen.getByText("What your agents can do on a call.")).toBeTruthy();

    rerender(
      <PageHeadingProvider>
        <FakeTopBar />
      </PageHeadingProvider>,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 }).closest("header")).toBeNull();
  });

  it("works outside the shell", () => {
    render(<PageHeader title="Files" />);
    expect(screen.getByRole("heading", { level: 1, name: "Files" })).toBeTruthy();
  });
});
