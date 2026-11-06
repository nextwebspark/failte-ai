import { StatusPill } from "@/components/ui/status-pill";
import type { AdminOrganization } from "@/lib/platformAdminApi";

export function OrganizationStatus({ status }: { status: AdminOrganization["status"] }) {
    if (status === "erased") return <StatusPill tone="mute">Erased</StatusPill>;
    if (status === "deletion_scheduled") return <StatusPill tone="warn">Deleting</StatusPill>;
    return <StatusPill tone="ok">Active</StatusPill>;
}
