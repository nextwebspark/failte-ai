import { exportSkillApiV1SkillsSkillUuidExportGet } from "@/client/sdk.gen";

import { NETWORK_ERROR, skillError } from "./errors";

/** Downloads a skill as `<name>.zip`; resolves to an error message or null. */
export async function downloadSkillZip(skillUuid: string, name: string): Promise<string | null> {
    try {
        const response = await exportSkillApiV1SkillsSkillUuidExportGet({
            path: { skill_uuid: skillUuid },
            parseAs: "blob",
        });
        if (response.error || !response.data) {
            return skillError(response.error, "Couldn't export the skill").message;
        }
        const url = URL.createObjectURL(response.data as Blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${name}.zip`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        // Revoking right away can cancel the download in some browsers.
        setTimeout(() => URL.revokeObjectURL(url), 0);
        return null;
    } catch {
        return NETWORK_ERROR;
    }
}
