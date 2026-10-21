import { toast } from "sonner";

import { cancelOrganizationDeletionRequestApiV1OrganizationsDeletionDelete } from "@/client/sdk.gen";
import { detailFromError } from "@/lib/apiError";

export function formatErasureDate(value: string | null | undefined) {
  if (!value) return "in 30 days";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Cancel a pending organization deletion and reload so the app reopens. */
export async function cancelOrganizationDeletion() {
  const res = await cancelOrganizationDeletionRequestApiV1OrganizationsDeletionDelete();
  if (res.error) {
    toast.error(detailFromError(res.error, "Could not cancel the deletion"));
    return false;
  }
  toast.success("Deletion cancelled; the organization is open again");
  window.location.reload();
  return true;
}


/** Error code the API returns while the organization is pending deletion. */
export const ORGANIZATION_PENDING_DELETION = "organization_pending_deletion";

/** True when `typed` confirms `expected` (case and surrounding space ignored). */
export function confirms(typed: string, expected: string) {
  return (
    expected.trim().length > 0 &&
    typed.trim().toLocaleLowerCase() === expected.trim().toLocaleLowerCase()
  );
}
