import { PageSkeleton } from "@/components/ui/page-skeleton";

/** Shown while this screen loads: shaped like it, so nothing jumps. */
export default function Loading() {
  return <PageSkeleton variant="list" />;
}
