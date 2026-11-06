import { HomeSkeleton } from "@/components/dashboard/HomeSkeleton";

/** Shown while Home loads: shaped like it, so nothing jumps. */
export default function Loading() {
  return <HomeSkeleton />;
}
