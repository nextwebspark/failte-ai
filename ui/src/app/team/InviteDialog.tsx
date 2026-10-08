"use client";

import { UserPlus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { createInvitationApiV1OrganizationsInvitationsPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";
import type { OrgRole } from "@/lib/auth/roles";

import { InviteLinkNotice } from "./InviteLinkNotice";
import { RoleSelect } from "./RoleSelect";

export function InviteDialog({ onInvited }: { onInvited: () => void }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("developer");
  const [submitting, setSubmitting] = useState(false);
  const [fallbackLink, setFallbackLink] = useState<string | null>(null);

  const reset = () => {
    setEmail("");
    setRole("developer");
    setFallbackLink(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    const res = await createInvitationApiV1OrganizationsInvitationsPost({ body: { email, role } });
    setSubmitting(false);
    if (res.error || !res.data) {
      toast.error(detailFromError(res.error, "Could not send the invitation"));
      return;
    }
    onInvited();
    if (res.data.email_sent || !res.data.accept_url) {
      toast.success(`Invitation sent to ${res.data.invitation.email}`);
      setOpen(false);
      reset();
      return;
    }
    setFallbackLink(res.data.accept_url);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" className="h-7 gap-1.5">
          <UserPlus className="h-3.5 w-3.5" />
          Invite member
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a team member</DialogTitle>
          <DialogDescription>
            They&apos;ll get an email with a link to join. The link works once and expires in 7 days.
          </DialogDescription>
        </DialogHeader>
        {fallbackLink ? (
          <>
            <InviteLinkNotice url={fallbackLink} />
            <DialogFooter>
              <Button onClick={() => { setOpen(false); reset(); }}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                placeholder="teammate@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-role">Role</Label>
              <RoleSelect id="invite-role" value={role} onChange={setRole} />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Sending..." : "Send invitation"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
