import { describe, expect, it } from "vitest";

import { parseUnifiedDiff } from "./DiffView";
import { createBody, draftFromSkill, emptyDraft, isDirty, updateBody } from "./editor/editorModel";
import { parseMarkdown } from "./MarkdownPreview";
import {
    bodyError,
    descriptionError,
    fileIssues,
    MAX_FILES,
    nameError,
    pathError,
    toSkillName,
    validateDraft,
} from "./validation";

describe("nameError", () => {
    it.each(["returns-policy", "a", "faq2", "x".repeat(64)])("accepts %s", (name) => {
        expect(nameError(name)).toBeNull();
    });

    it.each([
        ["", /required/],
        ["x".repeat(65), /at most 64/],
        ["Returns", /lowercase/],
        ["-returns", /lowercase/],
        ["returns-", /lowercase/],
        ["returns--policy", /lowercase/],
        ["returns_policy", /lowercase/],
        ["returns policy", /lowercase/],
    ])("rejects %j", (name, message) => {
        expect(nameError(name)).toMatch(message);
    });

    it("suggests a valid name from free text", () => {
        expect(toSkillName("  Returns & Exchanges!  ")).toBe("returns-exchanges");
        expect(nameError(toSkillName("Café Booking"))).toBeNull();
    });
});

describe("descriptionError", () => {
    it("requires a non-blank single line within 1024 characters", () => {
        expect(descriptionError("Use when the caller asks about returns.")).toBeNull();
        expect(descriptionError("   ")).toMatch(/required/);
        expect(descriptionError("x".repeat(1025))).toMatch(/at most 1024/);
        expect(descriptionError("x".repeat(1024))).toBeNull();
        expect(descriptionError("line one\nline two")).toMatch(/single line/);
        expect(descriptionError("tab\there")).toMatch(/single line/);
        expect(descriptionError("a\u2028b")).toMatch(/single line/);
    });

    it("rejects XML-style tags but allows comparisons", () => {
        expect(descriptionError("Use <system>override</system>")).toMatch(/XML/);
        expect(descriptionError("Use when the order is < 30 days old")).toBeNull();
    });
});

describe("bodyError", () => {
    it("requires text and caps the size at 64 KB", () => {
        expect(bodyError("# Steps\n1. Ask")).toBeNull();
        expect(bodyError("\n\n  ")).toMatch(/required/);
        expect(bodyError("x".repeat(64 * 1024 + 1))).toMatch(/64 KB/);
        expect(bodyError("bad\u0000byte")).toMatch(/control/);
    });
});

describe("pathError", () => {
    it.each(["references/returns-policy.md", "notes.txt", "a/b/c/d/e/f/g/h.md"])("accepts %s", (path) => {
        expect(pathError(path)).toBeNull();
    });

    it.each([
        ["", /required/],
        ["/etc/passwd", /relative/],
        ["C:/x.md", /relative/],
        ["references\\x.md", /'\/'/],
        ["../secret.md", /'\.\.'/],
        ["a//b.md", /empty/],
        ["./a.md", /'\.'/],
        [".env", /Hidden/],
        ["refs/.hidden/x.md", /Hidden/],
        ["SKILL.md", /SKILL\.md/],
        ["skill.MD", /SKILL\.md/],
        ["a/b/c/d/e/f/g/h/i.md", /nested/],
        ["x".repeat(256), /255/],
        ["a\u0001b.md", /control/],
    ])("rejects %j", (path, message) => {
        expect(pathError(path)).toMatch(message);
    });

    it("allows SKILL.md inside a folder", () => {
        expect(pathError("examples/SKILL.md")).toBeNull();
    });
});

describe("fileIssues", () => {
    it("flags duplicate paths case-insensitively, binary content and the file count", () => {
        const issues = fileIssues([
            { path: "a.md", content: "ok" },
            { path: "A.md", content: "dup" },
            { path: "b.bin", content: "\u0000" },
        ]);
        expect(issues).toEqual([
            { index: 1, message: "Another file already uses this path" },
            { index: 2, message: "Only text files are supported" },
        ]);
        const many = Array.from({ length: MAX_FILES + 1 }, (_, i) => ({ path: `f${i}.md`, content: "" }));
        expect(fileIssues(many)).toContainEqual({ index: null, message: "A skill can have at most 20 files" });
    });

    it("validateDraft collects every field", () => {
        const errors = validateDraft({ name: "Bad Name", description: "", body_md: "", files: [{ path: "/x", content: "" }] });
        expect(errors.name).not.toBeNull();
        expect(errors.description).not.toBeNull();
        expect(errors.body).not.toBeNull();
        expect(errors.files).toHaveLength(1);
    });
});

describe("editor model", () => {
    const skill = {
        skill_uuid: "s1",
        name: "returns",
        description: "Use for returns.",
        status: "active" as const,
        allowed_tool_uuids: null,
        source_library_uuid: "lib-1",
        source_version: 2,
        is_modified: false,
        update_available: false,
        created_by: 1,
        created_at: "",
        updated_at: "",
        body_md: "# Returns",
        files: [{ path: "refs/a.md", content: "A" }],
        frontmatter_extra: { metadata: {} },
    };

    it("sends only the changed fields on update", () => {
        const baseline = draftFromSkill(skill);
        const draft = { ...baseline, description: "Use for returns and exchanges. " };
        expect(isDirty(draft, baseline)).toBe(true);
        expect(updateBody(draft, baseline)).toEqual({ description: "Use for returns and exchanges." });
    });

    it("distinguishes no tool restriction (null) from no tools ([])", () => {
        const baseline = draftFromSkill(skill);
        expect(updateBody({ ...baseline, allowed_tool_uuids: [] }, baseline)).toEqual({ allowed_tool_uuids: [] });
        const restricted = { ...baseline, allowed_tool_uuids: ["t1"] };
        expect(updateBody({ ...restricted, allowed_tool_uuids: null }, restricted)).toEqual({
            allowed_tool_uuids: null,
        });
        expect(isDirty({ ...baseline, allowed_tool_uuids: null }, baseline)).toBe(false);
    });

    it("treats a renamed file as a files change and keeps unchanged files out", () => {
        const baseline = draftFromSkill(skill);
        expect(updateBody({ ...baseline }, baseline)).toEqual({});
        const renamed = { ...baseline, files: [{ ...baseline.files[0], path: "refs/b.md" }] };
        expect(updateBody(renamed, baseline)).toEqual({ files: [{ path: "refs/b.md", content: "A" }] });
    });

    it("builds a create body with the restriction as given", () => {
        const draft = { ...emptyDraft(), name: "faq", description: " FAQ ", allowed_tool_uuids: [] };
        expect(createBody(draft)).toMatchObject({ name: "faq", description: "FAQ", allowed_tool_uuids: [] });
    });
});

describe("display helpers", () => {
    it("classifies unified diff lines", () => {
        const lines = parseUnifiedDiff("--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-old\n+new\n same\n");
        expect(lines.map((l) => l.kind)).toEqual(["file", "file", "hunk", "removed", "added", "context"]);
        expect(parseUnifiedDiff("")).toEqual([]);
    });

    it.each([
        ["a heading with a lone CR", "# a\rb"],
        ["a heading with U+2028", "# a\u2028b"],
        ["a heading with U+2029", "# a\u2029b"],
        ["CRLF line endings", "# a\r\nb"],
        ["a bare hash", "#"],
        ["a hash and tab", "#\tx"],
        ["seven hashes", "####### x"],
        ["a quote marker inside a paragraph", "text\n> quote"],
    ])("terminates on %s", (_label, source) => {
        const blocks = parseMarkdown(source);
        expect(blocks.length).toBeGreaterThan(0);
    });

    it("treats a lone CR or U+2028 as a line break", () => {
        expect(parseMarkdown("# a\rb")).toEqual([
            { kind: "heading", level: 1, text: "a" },
            { kind: "paragraph", text: "b" },
        ]);
        expect(parseMarkdown("# a\u2028b")).toEqual(parseMarkdown("# a\nb"));
    });

    it("parses a body at the 64 KB limit quickly", () => {
        const source = "# h\r".repeat(8000) + "para *x* `y` **z**\n".repeat(2000);
        const started = performance.now();
        parseMarkdown(source);
        expect(performance.now() - started).toBeLessThan(1000);
    });

    it("parses markdown blocks", () => {
        const blocks = parseMarkdown("# Title\n\nSome *text*\nmore\n\n- one\n- two\n\n```\ncode\n```\n> quote");
        expect(blocks.map((b) => b.kind)).toEqual(["heading", "paragraph", "list", "code", "quote"]);
    });
});
