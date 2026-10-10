import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LibraryDiffResponse, SkillSummaryResponse } from "@/client/types.gen";

import { UpdateDialog } from "./UpdateDialog";

const mocks = vi.hoisted(() => ({ diff: vi.fn(), apply: vi.fn() }));

vi.mock("@/client/sdk.gen", () => ({
    getLibraryDiffApiV1SkillsSkillUuidLibraryDiffGet: mocks.diff,
    applyLibraryUpdateApiV1SkillsSkillUuidApplyLibraryUpdatePost: mocks.apply,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SKILL: SkillSummaryResponse = {
    skill_uuid: "skill-1",
    name: "returns-policy",
    description: "Returns",
    status: "active",
    allowed_tool_uuids: null,
    source_library_uuid: "lib-1",
    source_version: 2,
    is_modified: false,
    update_available: true,
    created_by: 1,
    created_at: "",
    updated_at: "",
};

function diff(overrides: Partial<LibraryDiffResponse> = {}): LibraryDiffResponse {
    return {
        skill_uuid: "skill-1",
        library_skill_uuid: "lib-1",
        source_version: 2,
        latest_version: 3,
        library_status: "published",
        is_modified: false,
        update_available: true,
        diff: "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-Old step\n+New step\n",
        ...overrides,
    };
}

const applied = { ...SKILL, body_md: "New step", files: [], frontmatter_extra: { metadata: {} } };

beforeEach(() => {
    vi.clearAllMocks();
});

describe("UpdateDialog", () => {
    it("shows the library diff and applies an unmodified copy without force", async () => {
        mocks.diff.mockResolvedValue({ data: diff() });
        mocks.apply.mockResolvedValue({ data: applied });
        const onApplied = vi.fn();
        render(<UpdateDialog skill={SKILL} canApply onOpenChange={vi.fn()} onApplied={onApplied} />);

        expect(await screen.findByText("-Old step")).toBeTruthy();
        expect(screen.getByText("+New step")).toBeTruthy();
        expect(screen.getByText(/from version 2; the library is at version 3/)).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Apply update" }));
        await waitFor(() =>
            expect(mocks.apply).toHaveBeenCalledWith({
                path: { skill_uuid: "skill-1" },
                body: { strategy: "replace", force: false },
            }),
        );
        expect(onApplied).toHaveBeenCalledWith(applied);
    });

    it("requires confirmation, then forces, for a modified copy", async () => {
        mocks.diff.mockResolvedValue({ data: diff({ is_modified: true }) });
        mocks.apply.mockResolvedValue({ data: applied });
        render(<UpdateDialog skill={SKILL} canApply onOpenChange={vi.fn()} onApplied={vi.fn()} />);

        const button = await screen.findByRole("button", { name: "Replace with library version" });
        expect(screen.getByText("This copy was edited in your workspace")).toBeTruthy();
        expect(button.hasAttribute("disabled")).toBe(true);

        fireEvent.click(screen.getByRole("checkbox", { name: "Replace my edits" }));
        expect(button.hasAttribute("disabled")).toBe(false);
        fireEvent.click(button);
        await waitFor(() =>
            expect(mocks.apply).toHaveBeenCalledWith({
                path: { skill_uuid: "skill-1" },
                body: { strategy: "replace", force: true },
            }),
        );
    });

    it("asks for confirmation when the copy was edited meanwhile (409 skill_modified)", async () => {
        mocks.diff.mockResolvedValue({ data: diff() });
        mocks.apply.mockResolvedValue({
            error: { detail: "This skill was edited in the workspace", code: "skill_modified" },
        });
        render(<UpdateDialog skill={SKILL} canApply onOpenChange={vi.fn()} onApplied={vi.fn()} />);

        fireEvent.click(await screen.findByRole("button", { name: "Apply update" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("This skill was edited in the workspace"));
        const button = await screen.findByRole("button", { name: "Replace with library version" });
        expect(button.hasAttribute("disabled")).toBe(true);
        expect(screen.getByRole("checkbox", { name: "Replace my edits" })).toBeTruthy();
    });

    it("only shows the diff to read-only roles", async () => {
        mocks.diff.mockResolvedValue({ data: diff({ is_modified: true }) });
        render(<UpdateDialog skill={SKILL} canApply={false} onOpenChange={vi.fn()} onApplied={vi.fn()} />);
        expect(await screen.findByText("+New step")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /Apply|Replace/ })).toBeNull();
        expect(screen.queryByRole("checkbox")).toBeNull();
    });
});
