import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LibrarySkillResponse } from "@/client/types.gen";
import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import { LibrarySkillEditor } from "./LibrarySkillEditor";

const mocks = vi.hoisted(() => ({
    authUser: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    publish: vi.fn(),
    deprecate: vi.fn(),
    replace: vi.fn(),
}));

vi.mock("@/client/sdk.gen", () => ({
    getAuthUserApiV1UserAuthUserGet: mocks.authUser,
    getLibrarySkillApiV1SkillLibraryLibrarySkillUuidGet: mocks.get,
    createLibrarySkillApiV1SkillLibraryPost: mocks.create,
    updateLibrarySkillApiV1SkillLibraryLibrarySkillUuidPatch: mocks.update,
    publishLibrarySkillApiV1SkillLibraryLibrarySkillUuidPublishPost: mocks.publish,
    deprecateLibrarySkillApiV1SkillLibraryLibrarySkillUuidDeprecatePost: mocks.deprecate,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace, push: vi.fn() }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: "1" }, loading: false }) }));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: () => true, role: "admin", loading: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function librarySkill(overrides: Partial<LibrarySkillResponse> = {}): LibrarySkillResponse {
    return {
        library_skill_uuid: "lib-1",
        name: "returns-policy",
        description: "Standard returns playbook.",
        version: 0,
        status: "draft",
        category: "customer-service",
        is_seeded: false,
        created_at: "",
        updated_at: "",
        body_md: "# Returns",
        files: [],
        frontmatter_extra: { metadata: {} },
        ...overrides,
    };
}

function renderEditor(uuid: string | null) {
    return render(
        <UnsavedChangesProvider>
            <LibrarySkillEditor libraryUuid={uuid} />
        </UnsavedChangesProvider>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.authUser.mockResolvedValue({ data: { id: 1, is_superuser: true } });
    mocks.get.mockResolvedValue({ data: librarySkill() });
});

describe("LibrarySkillEditor", () => {
    it("is only for platform admins", async () => {
        mocks.authUser.mockResolvedValue({ data: { id: 1, is_superuser: false } });
        renderEditor("lib-1");
        expect(await screen.findByText("You don't have access to this page")).toBeTruthy();
        expect(mocks.get).not.toHaveBeenCalled();
    });

    it("disables Publish while there are unsaved edits", async () => {
        renderEditor("lib-1");
        await screen.findByDisplayValue("returns-policy");
        const publish = screen.getByRole("button", { name: "Publish" });
        expect(publish.hasAttribute("disabled")).toBe(false);

        fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Edited playbook." } });
        expect(publish.hasAttribute("disabled")).toBe(true);
    });

    it("clears the category to null and sends only changed fields", async () => {
        mocks.update.mockResolvedValue({ data: librarySkill({ category: null }) });
        renderEditor("lib-1");
        await screen.findByDisplayValue("customer-service");

        fireEvent.change(screen.getByLabelText("Category"), { target: { value: "  " } });
        fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
        await waitFor(() =>
            expect(mocks.update).toHaveBeenCalledWith({
                path: { library_skill_uuid: "lib-1" },
                body: { category: null },
            }),
        );
    });

    it("publishes a saved draft", async () => {
        mocks.publish.mockResolvedValue({ data: librarySkill({ status: "published", version: 1 }) });
        renderEditor("lib-1");
        fireEvent.click(await screen.findByRole("button", { name: "Publish" }));
        await waitFor(() => expect(mocks.publish).toHaveBeenCalledWith({ path: { library_skill_uuid: "lib-1" } }));
        expect(await screen.findByRole("button", { name: "Deprecate" })).toBeTruthy();
    });
});
