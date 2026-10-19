import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resolveWorkflowConfigurations, type WorkflowConfigurations } from "@/types/workflow-configurations";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { type ConfigurationsPatch, SettingsSaveProvider, useSettingsSection } from "./SettingsSaveBar";

const BASE = resolveWorkflowConfigurations({ max_call_duration: 600 });

function PatchSection({ id, label, patch, blocker = null }: {
    id: string;
    label: string;
    patch: ConfigurationsPatch;
    blocker?: string | null;
}) {
    const [dirty, setDirty] = useState(false);
    useSettingsSection(id, { label, dirty, blocker, patch: () => patch });
    return <button onClick={() => setDirty(true)}>edit {label}</button>;
}

function OwnSection({ save, afterSave }: { save: () => Promise<void>; afterSave?: () => void }) {
    const [dirty, setDirty] = useState(false);
    useSettingsSection("variables", { label: "Variables", dirty, blocker: null, save, afterSave });
    return <button onClick={() => setDirty(true)}>edit Variables</button>;
}

type SaveConfigurations = (configurations: WorkflowConfigurations, workflowName: string) => Promise<void>;

function renderBar(
    children: React.ReactNode,
    saveConfigurations = vi.fn<SaveConfigurations>(async () => {}),
) {
    const onDiscard = vi.fn();
    render(
        <SettingsSaveProvider
            workflowName="Front desk"
            workflowConfigurations={BASE}
            saveWorkflowConfigurations={saveConfigurations}
            onDiscard={onDiscard}
            savedMessage="Settings saved."
        >
            {children}
        </SettingsSaveProvider>,
    );
    return { saveConfigurations, onDiscard };
}

beforeEach(() => vi.clearAllMocks());

describe("SettingsSaveProvider", () => {
    it("stays out of the way until something changes", () => {
        renderBar(<PatchSection id="general" label="General" patch={{ configurations: {} }} />);
        expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();

        fireEvent.click(screen.getByText("edit General"));
        expect(screen.getByRole("status").textContent).toContain("1 section not saved · General");
    });

    it("merges every configurations patch into one save, with the rename", async () => {
        const { saveConfigurations } = renderBar(
            <>
                <PatchSection
                    id="general"
                    label="General"
                    patch={{ workflowName: "Reception", configurations: { max_call_duration: 900 } }}
                />
                <PatchSection
                    id="voicemail"
                    label="Voicemail and screening"
                    patch={{ configurations: { voicemail_detection: { enabled: true } as never } }}
                />
            </>,
        );
        fireEvent.click(screen.getByText("edit General"));
        fireEvent.click(screen.getByText("edit Voicemail and screening"));
        expect(screen.getByRole("status").textContent).toContain("2 sections not saved · General, Voicemail and screening");

        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Settings saved."));
        expect(saveConfigurations).toHaveBeenCalledTimes(1);
        const [configurations, name] = saveConfigurations.mock.calls[0];
        expect(name).toBe("Reception");
        expect(configurations.max_call_duration).toBe(900);
        expect(configurations.voicemail_detection).toEqual({ enabled: true });
        expect(configurations.turn_stop_strategy).toBe(BASE.turn_stop_strategy);
    });

    it("saves sections with their own endpoint before the configurations", async () => {
        const order: string[] = [];
        const save = vi.fn(async () => {
            order.push("variables");
        });
        const afterSave = vi.fn();
        const saveConfigurations = vi.fn<SaveConfigurations>(async () => {
            order.push("configurations");
        });
        renderBar(
            <>
                <PatchSection id="general" label="General" patch={{ configurations: {} }} />
                <OwnSection save={save} afterSave={afterSave} />
            </>,
            saveConfigurations,
        );
        fireEvent.click(screen.getByText("edit General"));
        fireEvent.click(screen.getByText("edit Variables"));
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        await waitFor(() => expect(afterSave).toHaveBeenCalled());
        expect(order).toEqual(["variables", "configurations"]);
        // The rename-less patch keeps the current name.
        expect(saveConfigurations.mock.calls[0][1]).toBe("Front desk");
    });

    it("blocks saving and says why", () => {
        renderBar(
            <PatchSection id="general" label="General" patch={{ configurations: {} }} blocker="Add an agent name" />,
        );
        fireEvent.click(screen.getByText("edit General"));

        expect(screen.getByText("General: Add an agent name")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Save changes" })).toHaveProperty("disabled", true);
    });

    it("keeps the changes and shows the error when saving fails", async () => {
        renderBar(
            <PatchSection id="general" label="General" patch={{ configurations: {} }} />,
            vi.fn<SaveConfigurations>(async () => {
                throw new Error("Max call duration is too long");
            }),
        );
        fireEvent.click(screen.getByText("edit General"));
        fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Max call duration is too long"));
        expect(toast.success).not.toHaveBeenCalled();
        expect(screen.getByRole("button", { name: "Save changes" })).toHaveProperty("disabled", false);
    });

    it("discards on request", () => {
        const { onDiscard } = renderBar(<PatchSection id="general" label="General" patch={{ configurations: {} }} />);
        fireEvent.click(screen.getByText("edit General"));
        fireEvent.click(screen.getByRole("button", { name: "Discard" }));
        expect(onDiscard).toHaveBeenCalled();
    });
});
