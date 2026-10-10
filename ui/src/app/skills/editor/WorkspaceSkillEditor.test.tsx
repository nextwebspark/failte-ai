import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SkillResponse, ToolResponse } from "@/client/types.gen";
import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import { WorkspaceSkillEditor } from "./WorkspaceSkillEditor";

const mocks = vi.hoisted(() => ({
    getSkill: vi.fn(),
    createSkill: vi.fn(),
    updateSkill: vi.fn(),
    listTools: vi.fn(),
    replace: vi.fn(),
    can: vi.fn<(...permissions: string[]) => boolean>(() => true),
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
    getSkillApiV1SkillsSkillUuidGet: mocks.getSkill,
    createSkillApiV1SkillsPost: mocks.createSkill,
    updateSkillApiV1SkillsSkillUuidPatch: mocks.updateSkill,
    listToolsApiV1ToolsGet: mocks.listTools,
    exportSkillApiV1SkillsSkillUuidExportGet: vi.fn(),
    getLibraryDiffApiV1SkillsSkillUuidLibraryDiffGet: vi.fn(),
    applyLibraryUpdateApiV1SkillsSkillUuidApplyLibraryUpdatePost: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace, push: vi.fn() }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: "1" }, loading: false }) }));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, role: "developer", loading: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const TOOL: ToolResponse = {
    id: 1,
    tool_uuid: "tool-1",
    name: "Look up order",
    description: "Find an order by number",
    category: "http_api",
    icon: null,
    icon_color: null,
    status: "active",
    definition: {},
    created_at: "",
    updated_at: null,
};

function skill(overrides: Partial<SkillResponse> = {}): SkillResponse {
    return {
        skill_uuid: "skill-1",
        name: "returns-policy",
        description: "Use for returns.",
        status: "active",
        allowed_tool_uuids: null,
        source_library_uuid: null,
        source_version: null,
        is_modified: false,
        update_available: false,
        created_by: 1,
        created_at: "",
        updated_at: "",
        body_md: "# Returns",
        files: [{ path: "references/policy.md", content: "30 days" }],
        frontmatter_extra: { metadata: {} },
        ...overrides,
    };
}

function renderEditor(skillUuid: string | null) {
    return render(
        <UnsavedChangesProvider>
            <WorkspaceSkillEditor skillUuid={skillUuid} />
        </UnsavedChangesProvider>,
    );
}

function type(label: string | RegExp, value: string) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockImplementation(() => true);
    mocks.listTools.mockResolvedValue({ data: [TOOL] });
});

describe("WorkspaceSkillEditor", () => {
    it("validates name and description before creating", async () => {
        renderEditor(null);
        type("Name", "Returns Policy");
        expect(screen.getByText(/Use lowercase letters, digits and single hyphens/)).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Create skill/ }));
        expect(await screen.findByText("Fix the highlighted fields, then save again.")).toBeTruthy();
        expect(screen.getByText("Description is required")).toBeTruthy();
        expect(mocks.createSkill).not.toHaveBeenCalled();
    });

    it("keeps the description on one line and counts characters", () => {
        renderEditor(null);
        type("Description", "Use when\nthe caller asks");
        expect((screen.getByLabelText("Description") as HTMLTextAreaElement).value).toBe("Use when the caller asks");
        expect(screen.getByText("24/1024")).toBeTruthy();
    });

    it("validates new file paths like the server", () => {
        renderEditor(null);
        fireEvent.click(screen.getByRole("button", { name: /Add file/ }));
        type("New file path", "../secret.md");
        expect(screen.getByText(/must not contain empty, '\.' or '\.\.' parts/)).toBeTruthy();
        expect(screen.getByRole("button", { name: "Add" }).hasAttribute("disabled")).toBe(true);

        type("New file path", "SKILL.md");
        expect(screen.getByText(/SKILL\.md holds the instructions/)).toBeTruthy();

        type("New file path", "references/faq.md");
        fireEvent.click(screen.getByRole("button", { name: "Add" }));
        expect(screen.getByRole("button", { name: "references/faq.md" })).toBeTruthy();
        expect(screen.getByRole("button", { name: "Delete references/faq.md" })).toBeTruthy();
    });

    it("offers the suggested name after a name conflict", async () => {
        mocks.createSkill
            .mockResolvedValueOnce({
                error: {
                    detail: "A skill named 'returns-policy' already exists; try 'returns-policy-2'",
                    code: "skill_name_conflict",
                    suggested_name: "returns-policy-2",
                },
            })
            .mockResolvedValueOnce({ data: skill({ skill_uuid: "new-1", name: "returns-policy-2" }) });
        renderEditor(null);
        type("Name", "returns-policy");
        type("Description", "Use for returns.");

        fireEvent.click(screen.getByRole("button", { name: /Create skill/ }));
        fireEvent.click(await screen.findByRole("button", { name: "Use returns-policy-2" }));
        expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("returns-policy-2");

        fireEvent.click(screen.getByRole("button", { name: /Create skill/ }));
        await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/skills/new-1"));
        expect(mocks.createSkill).toHaveBeenLastCalledWith({
            body: expect.objectContaining({ name: "returns-policy-2", allowed_tool_uuids: null }),
        });
    });

    it("shows the limit message when the workspace is full", async () => {
        mocks.createSkill.mockResolvedValue({ error: { detail: "full", code: "skill_limit_reached" } });
        renderEditor(null);
        type("Name", "faq");
        type("Description", "Answers FAQs.");
        fireEvent.click(screen.getByRole("button", { name: /Create skill/ }));
        expect(await screen.findByText(/maximum of 50 active skills/)).toBeTruthy();
    });

    it("saves only changed fields, including an empty tool allowlist", async () => {
        mocks.getSkill.mockResolvedValue({ data: skill() });
        mocks.updateSkill.mockResolvedValue({ data: skill({ allowed_tool_uuids: ["tool-1"] }) });
        renderEditor("skill-1");

        await screen.findByDisplayValue("returns-policy");
        const save = screen.getByRole("button", { name: /^Save$/ });
        expect(save.hasAttribute("disabled")).toBe(true);

        fireEvent.click(screen.getByRole("radio", { name: "Only selected tools" }));
        expect(screen.getByText(/can't call any of the step's tools/)).toBeTruthy();
        fireEvent.click(screen.getByRole("checkbox", { name: /Look up order/ }));
        expect(screen.getByText(/can only use the 1 selected tool/)).toBeTruthy();
        expect(screen.getByText("Unsaved changes")).toBeTruthy();

        fireEvent.click(save);
        await waitFor(() =>
            expect(mocks.updateSkill).toHaveBeenCalledWith({
                path: { skill_uuid: "skill-1" },
                body: { allowed_tool_uuids: ["tool-1"] },
            }),
        );
        await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());
    });

    it("explains when the tool list can't be loaded", async () => {
        mocks.listTools.mockResolvedValue({ error: { detail: "Tools are down" } });
        mocks.getSkill.mockResolvedValue({ data: skill({ allowed_tool_uuids: ["tool-1"] }) });
        renderEditor("skill-1");
        expect(await screen.findByText(/Tools are down\. Selected tools show by ID/)).toBeTruthy();
        expect(screen.getByText("tool-1")).toBeTruthy();
    });

    it("keeps the open file selected after saving", async () => {
        const twoFiles = skill({
            files: [
                { path: "references/a.md", content: "A" },
                { path: "references/b.md", content: "B" },
            ],
        });
        mocks.getSkill.mockResolvedValue({ data: twoFiles });
        renderEditor("skill-1");
        fireEvent.click(await screen.findByRole("button", { name: "references/b.md" }));
        fireEvent.change(screen.getByLabelText("Content of references/b.md"), { target: { value: "B2" } });
        mocks.updateSkill.mockResolvedValue({
            data: { ...twoFiles, files: [twoFiles.files[0], { path: "references/b.md", content: "B2" }] },
        });

        fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
        await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());
        expect((screen.getByLabelText("Path") as HTMLInputElement).value).toBe("references/b.md");
        expect(screen.getByRole("button", { name: "references/b.md" }).getAttribute("aria-current")).toBe("true");
    });

    it("is read-only without agents:write", async () => {
        mocks.can.mockImplementation((...p: string[]) => p.every((x) => x === "agents:read"));
        mocks.getSkill.mockResolvedValue({ data: skill() });
        renderEditor("skill-1");

        expect(await screen.findByText(/You can view this skill/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: /^Save$/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Add file/ })).toBeNull();
        expect((screen.getByLabelText("Name") as HTMLInputElement).readOnly).toBe(true);
    });
});
