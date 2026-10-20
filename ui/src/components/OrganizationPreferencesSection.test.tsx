import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OrganizationPreferences } from "@/client/types.gen";

import { OrganizationPreferencesSection } from "./OrganizationPreferencesSection";

const mocks = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  savePreferences: vi.fn(),
  refreshConfig: vi.fn(),
  systemCodes: ["do_not_call"],
}));

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

vi.mock("@/client/sdk.gen", () => ({
  getPreferencesApiV1OrganizationsPreferencesGet: mocks.getPreferences,
  savePreferencesApiV1OrganizationsPreferencesPut: mocks.savePreferences,
}));

vi.mock("@/context/UserConfigContext", () => ({
  useUserConfig: () => ({ refreshConfig: mocks.refreshConfig }),
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div role="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => (
    <p>{children}</p>
  ),
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}));

vi.mock("@/hooks/useDispositionCodes", () => ({
  useDispositionCodes: () => ({
    codes: mocks.systemCodes,
    endTaskReasonCodes: [],
    systemCodes: mocks.systemCodes,
    isLoading: false,
  }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: 1 }, loading: false }),
}));

vi.mock("react-timezone-select", () => ({
  default: () => <div data-testid="timezone-select" />,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const preferences: OrganizationPreferences = {
  test_phone_number: null,
  timezone: "UTC",
  external_pbx_integrations_enabled: false,
  disposition_mapping_enabled: true,
  disposition_mapping: {},
};

describe("OrganizationPreferencesSection disposition mapping", () => {
  beforeEach(() => {
    mocks.getPreferences.mockReset();
    mocks.getPreferences.mockResolvedValue({ data: preferences });
    mocks.savePreferences.mockReset();
    mocks.savePreferences.mockImplementation(async ({ body }) => ({
      data: body,
    }));
    mocks.refreshConfig.mockReset();
    mocks.refreshConfig.mockResolvedValue(undefined);
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
  });

  it("persists a mapping from the modal without another page-level save", async () => {
    render(<OrganizationPreferencesSection />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Configure mapping" }),
    );
    fireEvent.change(screen.getByLabelText("Code for do_not_call"), {
      target: { value: "DNC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalledOnce());
    expect(mocks.savePreferences).toHaveBeenCalledWith({
      body: {
        test_phone_number: null,
        timezone: "UTC",
        external_pbx_integrations_enabled: false,
        disposition_mapping_enabled: true,
        disposition_mapping: { do_not_call: "DNC" },
      },
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Disposition mapping saved"),
    );
    expect(
      screen.queryByRole("heading", { name: "Configure disposition mapping" }),
    ).toBeNull();
  });

  it("keeps the modal open when persistence fails", async () => {
    mocks.savePreferences.mockResolvedValue({
      error: { detail: "Could not save mapping" },
    });
    render(<OrganizationPreferencesSection />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Configure mapping" }),
    );
    fireEvent.change(screen.getByLabelText("Code for do_not_call"), {
      target: { value: "DNC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalledOnce());
    expect(
      await screen.findByRole("button", { name: "Save mapping" }),
    ).toBeTruthy();
    expect(toast.error).toHaveBeenCalled();
  });
});

describe("OrganizationPreferencesSection call data retention", () => {
  beforeEach(() => {
    mocks.getPreferences.mockReset();
    mocks.getPreferences.mockResolvedValue({
      data: { ...preferences, call_data_retention_days: 90 },
    });
    mocks.savePreferences.mockReset();
    mocks.savePreferences.mockImplementation(async ({ body }) => ({
      data: body,
    }));
    mocks.refreshConfig.mockReset();
    mocks.refreshConfig.mockResolvedValue(undefined);
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
  });

  it("saves a longer retention period without asking", async () => {
    render(<OrganizationPreferencesSection />);

    const input = await screen.findByLabelText("Call data retention (days)");
    expect((input as HTMLInputElement).value).toBe("90");
    fireEvent.change(input, { target: { value: "180" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalledOnce());
    expect(
      mocks.savePreferences.mock.calls[0][0].body.call_data_retention_days,
    ).toBe(180);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("asks for confirmation before shortening the period", async () => {
    render(<OrganizationPreferencesSection />);

    const input = await screen.findByLabelText("Call data retention (days)");
    fireEvent.change(input, { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("older than 30 days");
    expect(dialog.textContent).toContain("next daily cleanup run");
    expect(mocks.savePreferences).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Shorten and save" }));

    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalledOnce());
    expect(
      mocks.savePreferences.mock.calls[0][0].body.call_data_retention_days,
    ).toBe(30);
  });

  it("does not save a shorter period when the confirmation is cancelled", async () => {
    render(<OrganizationPreferencesSection />);

    const input = await screen.findByLabelText("Call data retention (days)");
    fireEvent.change(input, { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(mocks.savePreferences).not.toHaveBeenCalled();
  });

  it("leaves the stored period alone when it was not changed", async () => {
    render(<OrganizationPreferencesSection />);

    await screen.findByLabelText("Call data retention (days)");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalledOnce());
    expect(mocks.savePreferences.mock.calls[0][0].body).not.toHaveProperty(
      "call_data_retention_days",
    );
  });

  it("does not persist an unsaved period with the disposition mapping", async () => {
    render(<OrganizationPreferencesSection />);

    fireEvent.change(
      await screen.findByLabelText("Call data retention (days)"),
      { target: { value: "7" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure mapping" }));
    fireEvent.change(screen.getByLabelText("Code for do_not_call"), {
      target: { value: "DNC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalledOnce());
    expect(mocks.savePreferences.mock.calls[0][0].body).not.toHaveProperty(
      "call_data_retention_days",
    );
    // The edit is still in the form, unsaved.
    expect(
      (screen.getByLabelText("Call data retention (days)") as HTMLInputElement)
        .value,
    ).toBe("7");
  });

  it("disables saving when the preferences failed to load", async () => {
    mocks.getPreferences.mockResolvedValue({
      error: { detail: "Server error" },
    });
    render(<OrganizationPreferencesSection />);

    expect(await screen.findByRole("alert")).toBeTruthy();
    const save = screen.getByRole("button", { name: "Save" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(save.closest("form")!);
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2));
    expect(mocks.savePreferences).not.toHaveBeenCalled();
  });

  it("rejects a period outside 1 to 365 days without saving", async () => {
    render(<OrganizationPreferencesSection />);

    const input = await screen.findByLabelText("Call data retention (days)");
    fireEvent.change(input, { target: { value: "366" } });
    // Submit the form directly: the browser's own min/max check would
    // otherwise stop the click before the component's validation runs.
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(mocks.savePreferences).not.toHaveBeenCalled();
  });
});
