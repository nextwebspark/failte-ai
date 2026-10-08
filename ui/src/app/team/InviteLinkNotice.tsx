"use client";

import { Copy } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copyTextToClipboard } from "@/lib/clipboard";

/** Shown when an invitation email could not be delivered. */
export function InviteLinkNotice({ url }: { url: string }) {
  const copy = async () => {
    await copyTextToClipboard(url);
    toast.success("Invitation link copied");
  };
  return (
    <div className="space-y-2 rounded-md border border-amber/40 bg-amber-dim p-3">
      <p className="text-sm">
        The invitation email could not be sent. Share this link with them directly:
      </p>
      <div className="flex gap-2">
        <Input readOnly value={url} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
        <Button type="button" variant="outline" size="icon" onClick={copy} aria-label="Copy link">
          <Copy className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
