"use client";

import { ArrowLeft, Compass, Home } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FriendlyNotice } from "@/components/layout/FriendlyNotice";
import { useOwnsPageHeading } from "@/components/layout/pageHeading";
import { Button } from "@/components/ui/button";

/** Any address the app doesn't have: say so kindly and offer a way on. */
export default function NotFound() {
  const router = useRouter();
  useOwnsPageHeading();

  return (
    <FriendlyNotice
      icon={Compass}
      title="We couldn't find that page"
      actions={
        <>
          <Button asChild>
            <Link href="/overview">
              <Home aria-hidden />
              Go to Overview
            </Link>
          </Button>
          <Button variant="outline" onClick={() => router.back()}>
            <ArrowLeft aria-hidden />
            Go back
          </Button>
        </>
      }
    >
      The link may be old, or the page may have moved. Everything else is still where you left it.
    </FriendlyNotice>
  );
}
