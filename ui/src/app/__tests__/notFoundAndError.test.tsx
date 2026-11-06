import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorPage from "../error";
import NotFound from "../not-found";

const back = vi.hoisted(() => vi.fn());
const capture = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ back }) }));
vi.mock("@sentry/nextjs", () => ({ captureException: capture }));

describe("not-found page", () => {
  it("says so kindly and offers Overview and Back", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { level: 1, name: "We couldn't find that page" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to Overview" }).getAttribute("href")).toBe("/overview");
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(back).toHaveBeenCalled();
  });
});

describe("error page", () => {
  it("offers Try again and Overview, without showing the raw error", () => {
    const reset = vi.fn();
    const error = new Error("TypeError: cannot read properties of undefined (reading 'x')");
    render(<ErrorPage error={error} reset={reset} />);

    expect(screen.getByRole("heading", { level: 1, name: "Something went wrong on this page" })).toBeTruthy();
    expect(screen.queryByText(/cannot read properties/)).toBeNull();
    expect(capture).toHaveBeenCalledWith(error);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Go to Overview" }).getAttribute("href")).toBe("/overview");
  });
});
