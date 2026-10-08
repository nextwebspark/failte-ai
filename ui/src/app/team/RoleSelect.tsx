import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ORG_ROLES, type OrgRole, ROLE_DESCRIPTIONS, ROLE_LABELS } from "@/lib/auth/roles";

export function RoleSelect({
  value,
  onChange,
  disabled,
  id,
}: {
  value: OrgRole;
  onChange: (role: OrgRole) => void;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as OrgRole)} disabled={disabled}>
      <SelectTrigger id={id} className="h-8 w-[140px]">
        {/* Items carry a description; the trigger shows just the role name. */}
        <SelectValue>{ROLE_LABELS[value]}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {ORG_ROLES.map((role) => (
          <SelectItem key={role} value={role}>
            <div className="flex flex-col">
              <span>{ROLE_LABELS[role]}</span>
              <span className="max-w-[260px] text-xs text-muted-foreground">
                {ROLE_DESCRIPTIONS[role]}
              </span>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
