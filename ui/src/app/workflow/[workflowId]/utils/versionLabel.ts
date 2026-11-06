/**
 * The version chip in the conversation toolbar, in words an owner reads at a
 * glance: "Version 1 · Live", "Version 3 · Draft". The API's status values
 * ("published", "draft", …) stay as they are; only the label changes.
 */
export function versionLabel(versionNumber: number, status?: string | null): string {
    const base = `Version ${versionNumber}`;
    if (status === "published") return `${base} · Live`;
    if (status === "draft") return `${base} · Draft`;
    return base;
}
