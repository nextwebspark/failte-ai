import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pathname: "/workflow/14/deployment",
  ask: vi.fn(),
  feedback: vi.fn(),
  tickets: vi.fn(),
  createTicket: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/client/sdk.gen", () => ({
  askHelpApiV1HelpAskPost: mocks.ask,
  helpFeedbackApiV1HelpFeedbackPost: mocks.feedback,
  getHelpTicketsApiV1HelpTicketsGet: mocks.tickets,
  createHelpTicketApiV1HelpTicketsPost: mocks.createTicket,
}));
vi.mock("@/components/layout/workspaceAgents", () => ({ useWorkspaceAgents: () => [{ id: 14, name: "Bia" }] }));

// Radix's checkbox measures itself; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

import { guideHref, startersFor } from "../helpContent";
import { HelpMarkdown, isSafeHref } from "../HelpMarkdown";
import { CONTACT_FORM_URL, HelpPanelProvider, useHelpPanel } from "../HelpPanel";

function Opener() {
  const help = useHelpPanel();
  return (
    <button type="button" onClick={() => help?.openHelp()}>
      open help
    </button>
  );
}

function renderPanel() {
  render(
    <HelpPanelProvider>
      <Opener />
    </HelpPanelProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "open help" }));
  return screen.findByRole("dialog");
}

const ANSWER = {
  id: "a".repeat(32),
  kind: "answer",
  answer: "1. Open [Phone number](/workflow/14/deployment).\n2. Press **Copy** and dial the code.",
  links: ["/workflow/14/deployment"],
  sources: ["phone-number#4"],
};

describe("help content", () => {
  it("suggests questions for the screen you're on", () => {
    expect(startersFor("/workflow/3/deployment")).toContain("How do I forward my mobile to my agent?");
    expect(startersFor("/billing")).toContain("How much do calls cost?");
    expect(startersFor("/settings/reports")[0]).toMatch(/email reports/);
    expect(startersFor("/somewhere-else").length).toBeGreaterThan(0);
  });

  it("points agent guides at the only agent, else the agents list", () => {
    expect(guideHref({ kind: "agent", segment: "facts" }, [{ id: 9 }])).toBe("/workflow/9/facts");
    expect(guideHref({ kind: "agent", segment: "deployment" }, [{ id: 9 }])).toBe("/workflow/9/deployment#phone");
    expect(guideHref({ kind: "agent", segment: "facts" }, [{ id: 1 }, { id: 2 }])).toBe("/workflow");
    expect(guideHref({ kind: "path", href: "/billing" }, null)).toBe("/billing");
  });
});

describe("HelpMarkdown", () => {
  it("renders steps, bold and in-app links, and never raw HTML or other links", () => {
    const onNavigate = vi.fn();
    const { container } = render(
      <HelpMarkdown
        text={'1. Open [Calls](/usage).\n2. Press **Share**.\n\n<img src=x onerror="alert(1)"> and [bad](javascript:alert(1))'}
        onNavigate={onNavigate}
      />,
    );
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(screen.getByText("Share").tagName).toBe("STRONG");
    const link = screen.getByRole("link", { name: "Calls" });
    expect(link.getAttribute("href")).toBe("/usage");
    fireEvent.click(link);
    expect(onNavigate).toHaveBeenCalled();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
    expect(isSafeHref("//evil.example")).toBe(false);
    expect(isSafeHref("https://lightmove.ai/contact")).toBe(true);
  });
});

describe("HelpPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.pathname = "/workflow/14/deployment";
    mocks.tickets.mockResolvedValue({ data: { tickets: [] } });
    mocks.feedback.mockResolvedValue({});
  });

  it("asks a starter question with the page, shows the answer and takes feedback", async () => {
    mocks.ask.mockResolvedValue({ data: ANSWER });
    const panel = await renderPanel();
    fireEvent.click(within(panel).getByRole("button", { name: /How do I forward my mobile/ }));
    expect(mocks.ask).toHaveBeenCalledWith({
      body: { question: "How do I forward my mobile to my agent?", page: "/workflow/14/deployment" },
    });
    expect(await within(panel).findByRole("link", { name: "Phone number" })).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "Yes, helpful" }));
    expect(mocks.feedback).toHaveBeenCalledWith({
      body: {
        answer_id: ANSWER.id,
        helpful: true,
        kind: "answer",
        sources: ["phone-number#4"],
        page: "/workflow/14/deployment",
      },
    });
    expect(within(panel).getByText("Thanks!")).toBeTruthy();
  });

  it("offers a person on every answer and carries the question over", async () => {
    mocks.ask.mockResolvedValue({
      data: { ...ANSWER, kind: "not_covered", answer: "I don't have that in my guides.", links: [], sources: [] },
    });
    const panel = await renderPanel();
    fireEvent.change(within(panel).getByLabelText("Your question"), { target: { value: "Can you port my number?" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Send question" }));
    fireEvent.click(await within(panel).findByRole("button", { name: "Ask a person instead" }));
    // No thumbs on an answer that isn't one.
    expect(within(panel).queryByRole("button", { name: "Yes, helpful" })).toBeNull();
    const subject = (await within(panel).findByLabelText("Subject")) as HTMLInputElement;
    await waitFor(() => expect(subject.value).toBe("Can you port my number?"));
  });

  it("shows an error when the assistant can't be reached", async () => {
    mocks.ask.mockRejectedValue(new Error("offline"));
    const panel = await renderPanel();
    fireEvent.change(within(panel).getByLabelText("Your question"), { target: { value: "Hello?" } });
    fireEvent.submit(within(panel).getByLabelText("Your question").closest("form")!);
    expect(await within(panel).findByText(/couldn't answer just now/)).toBeTruthy();
  });

  it("sends a ticket with the page, then lists it with its status", async () => {
    const ticket = {
      reference: "LM-4821",
      category: "phone",
      subject: "Transfers ring out",
      created_at: "2026-11-07T10:00:00Z",
      status: "open",
    };
    mocks.createTicket.mockResolvedValue({ data: { ticket } });
    mocks.tickets.mockResolvedValueOnce({ data: { tickets: [] } }).mockResolvedValue({ data: { tickets: [ticket] } });
    const panel = await renderPanel();
    fireEvent.mouseDown(within(panel).getByRole("tab", { name: "Contact support" }));
    fireEvent.click(within(panel).getByRole("tab", { name: "Contact support" }));
    const send = (await within(panel).findByRole("button", { name: "Send to support" })) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(within(panel).getByLabelText("Subject"), { target: { value: "Transfers ring out" } });
    fireEvent.change(within(panel).getByLabelText("Message"), { target: { value: "Calls never reach me." } });
    fireEvent.click(send);
    await waitFor(() =>
      expect(mocks.createTicket).toHaveBeenCalledWith({
        body: {
          category: "setup",
          subject: "Transfers ring out",
          message: "Calls never reach me.",
          include_page: true,
          page: "/workflow/14/deployment",
        },
      }),
    );
    expect(await within(panel).findByText("LM-4821", { selector: "strong" })).toBeTruthy();
    expect(await within(panel).findByText("Open")).toBeTruthy();
    const form = within(panel).getByRole("link", { name: /Contact form on our website/ });
    expect(form.getAttribute("href")).toBe(CONTACT_FORM_URL);
    expect(CONTACT_FORM_URL).toBe("https://lightmove.ai/contact?reason=support");
  });
});
