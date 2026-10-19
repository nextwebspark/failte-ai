import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";
import { resolveWorkflowConfigurations, type WorkflowConfigurations } from "@/types/workflow-configurations";

const mocks = vi.hoisted(() => ({
    saveConfigurations: vi.fn<(c: WorkflowConfigurations, name: string) => Promise<void>>(),
    saveVariables: vi.fn<(v: Record<string, string>) => Promise<void>>(),
    saveDictionary: vi.fn<(d: string) => Promise<void>>(),
    toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("sonner", () => ({ toast: mocks.toast }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("@/client/sdk.gen", () => ({
    downloadWorkflowReportApiV1WorkflowWorkflowIdReportGet: vi.fn(),
    getAmbientNoiseUploadUrlApiV1WorkflowAmbientNoiseUploadUrlPost: vi.fn(),
}));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ externalPbxIntegrationsEnabled: false }) }));
vi.mock("@/context/AppConfigContext", () => ({ useAppConfig: () => ({ config: { platformModelsEnabled: true } }) }));
vi.mock("@/hooks/useAudioPlayback", () => ({ useAudioPlayback: () => ({ playingId: null, toggle: vi.fn() }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: null, loading: false }) }));
vi.mock("@/components/LLMConfigSelector", () => ({ LLMConfigSelector: () => null }));

const CONFIGURATIONS = resolveWorkflowConfigurations({ max_call_duration: 600 });

vi.mock("../components/AgentSectionShell", () => ({
    AgentSectionShell: ({ children }: { children: (context: unknown) => ReactNode }) =>
        children({
            workflow: { id: 7, workflow_uuid: "wf-uuid-7" },
            workflowId: 7,
            workflowName: "Front desk",
            workflowConfigurations: CONFIGURATIONS,
            templateContextVariables: { business_name: "Bloom Dental" },
            dictionary: "",
            defaultCallDispositions: [],
            defaultAnswerClassifierPrompt: "Classify the answering party.",
            saveWorkflowConfigurations: mocks.saveConfigurations,
            saveTemplateContextVariables: mocks.saveVariables,
            saveDictionary: mocks.saveDictionary,
        }),
}));

import AgentAdvancedSettingsPage from "./page";

beforeAll(() => {
    globalThis.IntersectionObserver = class {
        observe() {}
        disconnect() {}
        unobserve() {}
        takeRecords() {
            return [];
        }
    } as unknown as typeof IntersectionObserver;
});

beforeEach(() => {
    vi.clearAllMocks();
    mocks.saveConfigurations.mockResolvedValue();
    mocks.saveVariables.mockResolvedValue();
});

function renderPage() {
    render(
        <UnsavedChangesProvider>
            <AgentAdvancedSettingsPage />
        </UnsavedChangesProvider>,
    );
}

describe("Advanced settings", () => {
    it("has one save bar instead of a Save button per card", () => {
        renderPage();
        expect(screen.getByRole("heading", { name: "Advanced settings" })).toBeTruthy();
        expect(screen.queryByRole("button", { name: /save/i })).toBeNull();

        fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Reception" } });

        expect(screen.getByRole("button", { name: "Save changes" })).toBeTruthy();
        expect(screen.getByRole("link", { name: /General.*Unsaved changes/ })).toBeTruthy();
    });

    it("saves a rename and a voicemail change together, so neither undoes the other", async () => {
        renderPage();
        fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Reception" } });
        fireEvent.click(screen.getByLabelText("Handle voicemail and screening"));
        expect(screen.getByRole("status").textContent).toContain("General, Voicemail and screening");

        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        await waitFor(() => expect(mocks.toast.success).toHaveBeenCalled());
        expect(mocks.saveConfigurations).toHaveBeenCalledTimes(1);
        const [configurations, name] = mocks.saveConfigurations.mock.calls[0];
        expect(name).toBe("Reception");
        expect(configurations.voicemail_detection?.enabled).toBe(true);
        expect(configurations.max_call_duration).toBe(600);
    });

    it("saves variables before the configurations", async () => {
        const order: string[] = [];
        mocks.saveVariables.mockImplementation(async () => {
            order.push("variables");
        });
        mocks.saveConfigurations.mockImplementation(async () => {
            order.push("configurations");
        });
        renderPage();
        fireEvent.change(screen.getByLabelText("Default value for business_name"), { target: { value: "Bloom" } });
        fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Reception" } });

        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        await waitFor(() => expect(order).toEqual(["variables", "configurations"]));
        expect(mocks.saveVariables).toHaveBeenCalledWith({ business_name: "Bloom" });
    });

    it("won't save without an agent name", () => {
        renderPage();
        fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "  " } });

        expect(screen.getByText("General: Add an agent name")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Save changes" })).toHaveProperty("disabled", true);
    });

    it("discards every change", () => {
        renderPage();
        fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Reception" } });
        fireEvent.change(screen.getByLabelText("Default value for business_name"), { target: { value: "Bloom" } });

        fireEvent.click(screen.getByRole("button", { name: "Discard" }));

        expect((screen.getByLabelText("Agent name") as HTMLInputElement).value).toBe("Front desk");
        expect((screen.getByLabelText("Default value for business_name") as HTMLInputElement).value).toBe("Bloom Dental");
        expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    });

    it("saves a trimmed name and then shows nothing unsaved", async () => {
        mocks.saveConfigurations.mockImplementation(async () => {});
        renderPage();
        fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Front desk " } });

        // Only trailing space: the trimmed name is unchanged, so nothing to save.
        expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    });

    it("won't drop a new variable value that has no name", () => {
        renderPage();
        fireEvent.change(screen.getByLabelText("New variable value"), { target: { value: "Free parking" } });

        expect(screen.getByText("Variables: Give the new variable a name")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Save changes" })).toHaveProperty("disabled", true);
    });
});
