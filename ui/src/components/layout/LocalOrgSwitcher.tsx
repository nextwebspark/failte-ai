"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  createOrganizationApiV1OrganizationsPost,
  listMyOrganizationsApiV1OrganizationsMineGet,
  selectMyOrganizationApiV1OrganizationsOrganizationIdSelectPost,
} from "@/client/sdk.gen";
import type { UserOrganizationResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { cn } from "@/lib/utils";

/** Reload into the newly selected organization so every screen refetches. */
function enterWorkspace() {
  window.location.href = "/after-sign-in";
}

/**
 * Workspace switcher for local (email/password, Google) auth — the Stack
 * deployment uses Stack's own team switcher instead.
 */
export function LocalOrgSwitcher({ className }: { className?: string }) {
  const { orgContext } = useOrgConfig();
  const [organizations, setOrganizations] = useState<UserOrganizationResponse[] | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  const currentName = orgContext?.organization_name || "My workspace";

  const load = async () => {
    const res = await listMyOrganizationsApiV1OrganizationsMineGet();
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not load your workspaces"));
      return;
    }
    setOrganizations(res.data ?? []);
  };

  const select = async (organization: UserOrganizationResponse) => {
    if (organization.is_selected) return;
    setBusy(true);
    const res = await selectMyOrganizationApiV1OrganizationsOrganizationIdSelectPost({
      path: { organization_id: organization.organization_id },
    });
    if (res.error) {
      setBusy(false);
      toast.error(detailFromError(res.error, "Could not switch workspace"));
      return;
    }
    enterWorkspace();
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const res = await createOrganizationApiV1OrganizationsPost({ body: { name: newName } });
    if (res.error) {
      setBusy(false);
      toast.error(detailFromError(res.error, "Could not create the workspace"));
      return;
    }
    enterWorkspace();
  };

  return (
    <>
      <DropdownMenu onOpenChange={(open) => open && void load()}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={cn(
              "flex h-7 min-w-0 items-center gap-1.5 rounded-[7px] px-1.5 font-mono text-[13px] font-medium text-ink-3 hover:text-foreground",
              className,
            )}
          >
            <span className="truncate">{currentName}</span>
            <ChevronsUpDown className="h-3 w-3 shrink-0 opacity-60" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
            Workspaces
          </DropdownMenuLabel>
          {organizations === null ? (
            <DropdownMenuItem disabled>Loading...</DropdownMenuItem>
          ) : (
            organizations.map((organization) => (
              <DropdownMenuItem
                key={organization.organization_id}
                onClick={() => void select(organization)}
                disabled={busy}
                className="cursor-pointer"
              >
                <Check
                  className={cn("mr-2 h-4 w-4", organization.is_selected ? "opacity-100" : "opacity-0")}
                />
                <span className="min-w-0 flex-1 truncate">
                  {organization.name || `Workspace ${organization.organization_id}`}
                </span>
                <span className="ml-2 text-xs text-muted-foreground">
                  {ROLE_LABELS[organization.role]}
                </span>
              </DropdownMenuItem>
            ))
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setCreateOpen(true)} className="cursor-pointer">
            <Plus className="mr-2 h-4 w-4" />
            Create workspace
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create a workspace</DialogTitle>
            <DialogDescription>
              A separate workspace with its own agents, numbers and members. You&apos;ll be its admin.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={create} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="workspace-name">Name</Label>
              <Input
                id="workspace-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Acme Voice"
                maxLength={100}
                required
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={busy || !newName.trim()}>
                {busy ? "Creating..." : "Create workspace"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
