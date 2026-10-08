import { Badge } from "@/components/ui/badge";
import { type OrgRole, ROLE_LABELS } from "@/lib/auth/roles";

export function RoleBadge({ role }: { role: OrgRole }) {
  return (
    <Badge variant={role === "admin" ? "default" : "secondary"} className="font-normal">
      {ROLE_LABELS[role]}
    </Badge>
  );
}
