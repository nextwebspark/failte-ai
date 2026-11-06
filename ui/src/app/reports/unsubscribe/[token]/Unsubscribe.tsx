"use client";

import { useEffect, useRef, useState } from "react";

import { unsubscribeEmailReportRecipientApiV1PublicEmailReportsUnsubscribeTokenPost } from "@/client/sdk.gen";
import { Skeleton } from "@/components/ui/skeleton";

import { ReportLinkCard } from "../../ReportLinkCard";

type Outcome = "removed" | "already" | "invalid" | "failed";

/** One click from the email: opening the page unsubscribes. */
export function Unsubscribe({ token }: { token: string }) {
  const started = useRef(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [business, setBusiness] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void unsubscribeEmailReportRecipientApiV1PublicEmailReportsUnsubscribeTokenPost({ path: { token } }).then(
      (result) => {
        if (result.error || !result.data) {
          setOutcome("failed");
          return;
        }
        setBusiness(result.data.business_name ?? null);
        const status = result.data.status;
        setOutcome(status === "removed" || status === "already" ? status : "invalid");
      },
    );
  }, [token]);

  if (outcome === null) {
    return (
      <ReportLinkCard title="Unsubscribing…">
        <Skeleton className="h-5 w-3/4" />
      </ReportLinkCard>
    );
  }
  if (outcome === "removed" || outcome === "already") {
    return (
      <ReportLinkCard title="You're unsubscribed">
        <p role="status">
          This address won&apos;t get {business ? `${business}'s` : "these"} call reports any more.
        </p>
        <p>Changed your mind? Ask the workspace owner to add you again.</p>
      </ReportLinkCard>
    );
  }
  if (outcome === "failed") {
    return (
      <ReportLinkCard title="That didn't work">
        <p role="alert">We couldn&apos;t unsubscribe you just now. Refresh the page to try again.</p>
      </ReportLinkCard>
    );
  }
  return (
    <ReportLinkCard title="This link doesn't work">
      <p role="alert">
        It may have been copied wrongly. Use the Unsubscribe link at the bottom of the latest report, or ask the
        workspace owner to remove you.
      </p>
    </ReportLinkCard>
  );
}
