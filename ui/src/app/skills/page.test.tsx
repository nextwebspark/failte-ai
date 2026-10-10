import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LibrarySkillSummaryResponse, SkillResponse, SkillSummaryResponse } from "@/client/types.gen";

import SkillsPage from "./page";

const mocks = vi.hoisted(() => ({
    listSkills: vi.fn(),
    listLibrary: vi.fn(),
    authUser: vi.fn(),
    importSkill: vi.fn(),
    archive: vi.fn(),
    copy: vi.fn(),
    exportSkill: vi.fn(),
    diff: vi.fn(),
    apply: vi.fn(),
    getLibrary: vi.fn(),
    publish: vi.fn(),
    deprecate: vi.fn(),
    syncSeeds: vi.fn(),
    can: vi.fn<(...permissions: string[]) => boolean>(() => true),
    role: "developer" as string | null,
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
    listSkillsApiV1SkillsGet: mocks.listSkills,
    listLibrarySkillsApiV1SkillLibraryGet: mocks.listLibrary,
    getAuthUserApiV1UserAuthUserGet: mocks.authUser,
    importSkillApiV1SkillsImportPost: mocks.importSkill,
    archiveSkillApiV1SkillsSkillUuidDelete: mocks.archive,
    copyLibrarySkillApiV1SkillsFromLibraryLibrarySkillUuidPost: mocks.copy,
    exportSkillApiV1SkillsSkillUuidExportGet: mocks.exportSkill,
    getLibraryDiffApiV1SkillsSkillUuidLibraryDiffGet: mocks.diff,
    applyLibraryUpdateApiV1SkillsSkillUuidApplyLibraryUpdatePost: mocks.apply,
    getLibrarySkillApiV1SkillLibraryLibrarySkillUuidGet: mocks.getLibrary,
    publishLibrarySkillApiV1SkillLibraryLibrarySkillUuidPublishPost: mocks.publish,
    deprecateLibrarySkillApiV1SkillLibraryLibrarySkillUuidDeprecatePost: mocks.deprecate,
    syncLibrarySeedsApiV1SkillLibrarySyncSeedsPost: mocks.syncSeeds,
}));

vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1" }, loading: false }),
}));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, role: mocks.role, loading: false }),
}));

vi.mock("sonner", () => ({
    toast: { success: vi.fn(), error: vi.fn() },
}));

function summary(overrides: Partial<SkillSummaryResponse> = {}): SkillSummaryResponse {
    return {
        skill_uuid: "skill-1",
        name: "returns-policy",
        description: "Use when the caller asks about returns.",
        status: "active",
        allowed_tool_uuids: null,
        source_library_uuid: null,
        source_version: null,
        is_modified: false,
        update_available: false,
        created_by: 1,
        created_at: "2026-10-10T00:00:00Z",
        updated_at: "2026-10-10T00:00:00Z",
        ...overrides,
    };
}

function full(overrides: Partial<SkillResponse> = {}): SkillResponse {
    return { ...summary(), body_md: "# Returns", files: [], frontmatter_extra: { metadata: {} }, ...overrides };
}

function librarySkill(overrides: Partial<LibrarySkillSummaryResponse> = {}): LibrarySkillSummaryResponse {
    return {
        library_skill_uuid: "lib-1",
        name: "returns-policy",
        description: "Standard returns playbook.",
        version: 3,
        status: "published",
        category: "customer-service",
        is_seeded: true,
        created_at: "",
        updated_at: "",
        ...overrides,
    };
}

/** Radix tabs switch on mouse down. */
function chooseTab(name: RegExp) {
    fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });
}

function onlyRead(...permissions: string[]) {
    return permissions.every((p) => p === "agents:read");
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockImplementation(() => true);
    mocks.role = "developer";
    mocks.listSkills.mockResolvedValue({ data: { skills: [] } });
    mocks.listLibrary.mockResolvedValue({ data: { skills: [] } });
    mocks.authUser.mockResolvedValue({ data: { id: 1, is_superuser: false } });
    window.history.replaceState(null, "", "/skills");
});

describe("My skills", () => {
    it("lists skills with source, modified and update badges", async () => {
        mocks.listSkills.mockResolvedValue({
            data: {
                skills: [
                    summary({ skill_uuid: "a", name: "custom-faq" }),
                    summary({
                        skill_uuid: "b",
                        name: "returns-policy",
                        source_library_uuid: "lib-1",
                        source_version: 2,
                        is_modified: true,
                        update_available: true,
                        allowed_tool_uuids: [],
                    }),
                ],
            },
        });
        render(<SkillsPage />);

        const cards = await screen.findAllByTestId("skill-card");
        expect(within(cards[0]).getByText("Custom")).toBeTruthy();
        expect(within(cards[1]).getByText("From library v2")).toBeTruthy();
        expect(within(cards[1]).getByText("Modified")).toBeTruthy();
        expect(within(cards[1]).getByText("Update available")).toBeTruthy();
        expect(within(cards[1]).getByText("No other tools while loaded")).toBeTruthy();
    });

    it("shows no access and loads nothing without agents:read", async () => {
        mocks.role = "viewer";
        mocks.can.mockImplementation(() => false);
        render(<SkillsPage />);
        expect(await screen.findByText("You don't have access to this page")).toBeTruthy();
        expect(mocks.listSkills).not.toHaveBeenCalled();
    });

    it("is read-only for viewers", async () => {
        mocks.role = "viewer";
        mocks.can.mockImplementation(onlyRead);
        mocks.listSkills.mockResolvedValue({ data: { skills: [summary({ update_available: true, source_library_uuid: "lib-1" })] } });
        render(<SkillsPage />);

        expect(await screen.findByText(/You can view skills/)).toBeTruthy();
        for (const name of [/New skill/, /^Import$/, /Archive/]) {
            expect(screen.queryByRole("button", { name })).toBeNull();
        }
        expect(screen.queryByRole("link", { name: /New skill/ })).toBeNull();
        expect(screen.getByRole("link", { name: "View returns-policy" })).toBeTruthy();
        expect(screen.getByRole("button", { name: /View update/ })).toBeTruthy();
    });

    it("shows import warnings such as dropped allowed-tools", async () => {
        mocks.importSkill.mockResolvedValue({
            data: { ...full({ name: "imported-skill" }), warnings: ["Dropped allowed-tools entry 'Bash': not a tool of this workspace"] },
        });
        render(<SkillsPage />);
        await screen.findByText("No skills yet");

        const file = new File(["---\nname: imported-skill\n---\nbody"], "SKILL.md", { type: "text/markdown" });
        fireEvent.change(screen.getByTestId("skill-import-input"), { target: { files: [file] } });

        const dialog = await screen.findByRole("dialog");
        expect(within(dialog).getByText("Imported imported-skill")).toBeTruthy();
        expect(within(dialog).getByText(/Dropped allowed-tools entry 'Bash'/)).toBeTruthy();
        expect(mocks.importSkill).toHaveBeenCalledWith({ body: { file } });
        expect(mocks.listSkills).toHaveBeenCalledTimes(2);
    });

    it("toasts a clean import without a dialog", async () => {
        mocks.importSkill.mockResolvedValue({ data: { ...full({ name: "clean" }), warnings: [] } });
        render(<SkillsPage />);
        await screen.findByText("No skills yet");
        fireEvent.change(screen.getByTestId("skill-import-input"), {
            target: { files: [new File(["x"], "clean.zip")] },
        });
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Imported clean"));
        expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("explains the workspace skill limit and disables adding more", async () => {
        mocks.importSkill.mockResolvedValue({
            error: { detail: "This workspace already has 50 active skills", code: "skill_limit_reached" },
        });
        render(<SkillsPage />);
        await screen.findByText("No skills yet");
        fireEvent.change(screen.getByTestId("skill-import-input"), {
            target: { files: [new File(["x"], "a.zip")] },
        });

        expect(await screen.findByText(/maximum of 50 active skills/)).toBeTruthy();
        expect(screen.getByRole("button", { name: /^Import$/ }).hasAttribute("disabled")).toBe(true);
        expect(screen.getByRole("button", { name: /New skill/ }).hasAttribute("disabled")).toBe(true);
    });

    it("archives after confirmation", async () => {
        mocks.listSkills
            .mockResolvedValueOnce({ data: { skills: [summary()] } })
            .mockResolvedValue({ data: { skills: [] } });
        mocks.archive.mockResolvedValue({ data: undefined });
        render(<SkillsPage />);

        fireEvent.click(await screen.findByRole("button", { name: "Archive returns-policy" }));
        expect(mocks.archive).not.toHaveBeenCalled();
        fireEvent.click(await screen.findByRole("button", { name: "Archive" }));

        await waitFor(() => expect(mocks.archive).toHaveBeenCalledWith({ path: { skill_uuid: "skill-1" } }));
        expect(await screen.findByText("No skills yet")).toBeTruthy();
    });
});

describe("Library", () => {
    it("filters by search and category", async () => {
        mocks.listLibrary.mockResolvedValue({
            data: {
                skills: [
                    librarySkill(),
                    librarySkill({ library_skill_uuid: "lib-2", name: "booking", description: "Book slots", category: "scheduling" }),
                ],
            },
        });
        render(<SkillsPage />);
        chooseTab(/Library/);

        expect(await screen.findByText("booking")).toBeTruthy();
        Element.prototype.scrollIntoView = vi.fn();
        const filter = screen.getByRole("combobox", { name: "Filter by category" });
        fireEvent.keyDown(filter, { key: "Enter" });
        fireEvent.click(await screen.findByRole("option", { name: "scheduling" }));
        await waitFor(() => expect(screen.queryByText("returns-policy")).toBeNull());
        fireEvent.keyDown(filter, { key: "Enter" });
        fireEvent.click(await screen.findByRole("option", { name: "All categories" }));
        fireEvent.change(screen.getByRole("textbox", { name: "Search library skills" }), {
            target: { value: "returns" },
        });
        expect(screen.getByText("returns-policy")).toBeTruthy();
        expect(screen.queryByText("booking")).toBeNull();
    });

    it("offers the suggested name when the name is taken, then adds under it", async () => {
        mocks.listLibrary.mockResolvedValue({ data: { skills: [librarySkill()] } });
        mocks.copy
            .mockResolvedValueOnce({
                error: {
                    detail: "A skill named 'returns-policy' already exists; try 'returns-policy-2'",
                    code: "skill_name_conflict",
                    suggested_name: "returns-policy-2",
                },
            })
            .mockResolvedValueOnce({ data: full({ name: "returns-policy-2" }) });
        render(<SkillsPage />);
        chooseTab(/Library/);

        fireEvent.click(await screen.findByRole("button", { name: "Add returns-policy to workspace" }));
        const dialog = await screen.findByRole("dialog");
        expect((within(dialog).getByLabelText("Name") as HTMLInputElement).value).toBe("returns-policy-2");
        fireEvent.click(within(dialog).getByRole("button", { name: "Add as returns-policy-2" }));

        await waitFor(() =>
            expect(mocks.copy).toHaveBeenLastCalledWith({
                path: { library_skill_uuid: "lib-1" },
                body: { name: "returns-policy-2" },
            }),
        );
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Added returns-policy-2 to your workspace"));
    });

    it("toasts the limit message when the workspace is full", async () => {
        mocks.listLibrary.mockResolvedValue({ data: { skills: [librarySkill()] } });
        mocks.copy.mockResolvedValue({ error: { detail: "full", code: "skill_limit_reached" } });
        render(<SkillsPage />);
        chooseTab(/Library/);
        fireEvent.click(await screen.findByRole("button", { name: "Add returns-policy to workspace" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/maximum of 50/)));
    });

    it("hides Add for viewers and admin tools for non-platform-admins", async () => {
        mocks.can.mockImplementation(onlyRead);
        mocks.listLibrary.mockResolvedValue({ data: { skills: [librarySkill()] } });
        render(<SkillsPage />);
        chooseTab(/Library/);

        expect(await screen.findByText("returns-policy")).toBeTruthy();
        await waitFor(() => expect(mocks.authUser).toHaveBeenCalled());
        expect(screen.queryByRole("button", { name: /Add returns-policy/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Sync seeds/ })).toBeNull();
        expect(screen.queryByRole("link", { name: /New library skill/ })).toBeNull();
        expect(screen.queryByRole("link", { name: /Edit library skill/ })).toBeNull();
    });

    it("shows drafts, publish/deprecate and seed sync to platform admins", async () => {
        mocks.authUser.mockResolvedValue({ data: { id: 1, is_superuser: true } });
        mocks.listLibrary.mockResolvedValue({
            data: {
                skills: [
                    librarySkill(),
                    librarySkill({ library_skill_uuid: "lib-2", name: "draft-skill", status: "draft", version: 0 }),
                ],
            },
        });
        mocks.publish.mockResolvedValue({ data: { ...librarySkill({ library_skill_uuid: "lib-2", name: "draft-skill", version: 1 }), body_md: "x", files: [], frontmatter_extra: { metadata: {} } } });
        mocks.syncSeeds.mockResolvedValue({ data: { created: ["a"], updated: [], unchanged: ["b"], skipped: [] } });
        render(<SkillsPage />);
        chooseTab(/Library/);

        expect(await screen.findByRole("button", { name: /Sync seeds/ })).toBeTruthy();
        expect(screen.getByText("draft")).toBeTruthy();
        expect(screen.getByRole("link", { name: /New library skill/ }).getAttribute("href")).toBe("/skills/library/new");
        expect(screen.getByRole("link", { name: "Edit library skill draft-skill" })).toBeTruthy();
        expect(screen.getByRole("button", { name: "Deprecate" })).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Publish" }));
        await waitFor(() => expect(mocks.publish).toHaveBeenCalledWith({ path: { library_skill_uuid: "lib-2" } }));
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Published draft-skill v1"));
        // Publishing may flag updates on workspace copies, so both lists reload.
        await waitFor(() => expect(mocks.listSkills).toHaveBeenCalledTimes(2));
        expect(mocks.listLibrary).toHaveBeenCalledTimes(2);

        fireEvent.click(screen.getByRole("button", { name: /Sync seeds/ }));
        await waitFor(() =>
            expect(toast.success).toHaveBeenCalledWith("Seeds synced: 1 new, 0 updated, 1 unchanged"),
        );
    });
});
