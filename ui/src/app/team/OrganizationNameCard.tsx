"use client";

import { useState } from "react";
import { toast } from "sonner";

import { renameCurrentOrganizationApiV1OrganizationsCurrentPatch } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";

export function OrganizationNameCard() {
  const { orgContext, refreshConfig } = useOrgConfig();
  const current = orgContext?.organization_name ?? "";
  const [name, setName] = useState(current);
  const [saving, setSaving] = useState(false);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const res = await renameCurrentOrganizationApiV1OrganizationsCurrentPatch({
      body: { name },
    });
    setSaving(false);
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not rename the workspace"));
      return;
    }
    toast.success("Workspace renamed");
    await refreshConfig();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspace name</CardTitle>
        <CardDescription>Shown to members and in invitation emails.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} className="flex gap-2">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Voice"
            maxLength={100}
            required
          />
          <Button type="submit" disabled={saving || !name.trim() || name.trim() === current}>
            {saving ? "Saving..." : "Save"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
