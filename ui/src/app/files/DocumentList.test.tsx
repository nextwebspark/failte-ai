import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DocumentList from "./DocumentList";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    config: { documentProcessingEnabled: true, mpsEnabled: false },
}));
vi.mock("@/client/sdk.gen", () => ({
    listDocumentsApiV1KnowledgeBaseDocumentsGet: mocks.list,
    deleteDocumentApiV1KnowledgeBaseDocumentsDocumentUuidDelete: vi.fn(),
}));
vi.mock("@/context/AppConfigContext", () => ({
    useAppConfig: () => ({ config: mocks.config, loading: false }),
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({
    useOrganizationTimezone: () => "UTC",
}));
vi.mock("./DocumentEditor", () => ({
    default: () => null,
    isEditableDocument: (filename: string) => filename.endsWith(".md"),
}));

const document = {
    id: 1,
    document_uuid: "doc-1",
    filename: "faq.md",
    file_size_bytes: 120,
    file_hash: "h",
    mime_type: "text/markdown",
    processing_status: "completed",
    retrieval_mode: "chunked",
    total_chunks: 2,
    created_at: "2026-10-01T00:00:00Z",
    has_live_content: true,
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.config.documentProcessingEnabled = true;
    mocks.config.mpsEnabled = false;
    mocks.list.mockResolvedValue({ data: { documents: [document] } });
});

describe("document editing", () => {
    it("offers Edit when documents can be re-processed, with or without an MPS", async () => {
        render(<DocumentList refreshTrigger={0} />);
        await screen.findByText("faq.md");
        expect(screen.getByTitle("Edit")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Edit faq.md" })).toBeTruthy();
    });

    it("hides Edit when document processing isn't available", async () => {
        mocks.config.documentProcessingEnabled = false;
        render(<DocumentList refreshTrigger={0} />);
        await screen.findByText("faq.md");
        expect(screen.queryByTitle("Edit")).toBeNull();
        expect(screen.queryByRole("button", { name: "Edit faq.md" })).toBeNull();
    });
});

describe("re-index hint", () => {
    it("explains documents embedded with another model", async () => {
        mocks.list.mockResolvedValue({
            data: { documents: [{ ...document, needs_reindex: true }] },
        });
        render(<DocumentList refreshTrigger={0} />);
        expect(await screen.findByText(/Re-index needed/)).toBeTruthy();
    });

    it("stays quiet otherwise", async () => {
        render(<DocumentList refreshTrigger={0} />);
        await screen.findByText("faq.md");
        expect(screen.queryByText(/Re-index needed/)).toBeNull();
    });
});
