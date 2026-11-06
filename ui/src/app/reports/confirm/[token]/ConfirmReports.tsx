"use client";

import { useState } from "react";

import { confirmEmailReportRecipientApiV1PublicEmailReportsConfirmTokenPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";

import { ReportLinkCard } from "../../ReportLinkCard";

type Outcome = "confirmed" | "already" | "invalid" | "failed";

/**
 * Confirming an address for call reports. It takes a button press, not just
 * opening the link, so a mail scanner that follows links can't sign anyone up.
 */
export function ConfirmReports({ token }: { token: string }) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [business, setBusiness] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    const result = await confirmEmailReportRecipientApiV1PublicEmailReportsConfirmTokenPost({ path: { token } });
    setBusy(false);
    if (result.error || !result.data) {
      setOutcome("failed");
      return;
    }
    setBusiness(result.data.business_name ?? null);
    setOutcome(result.data.status === "removed" ? "invalid" : result.data.status);
  }

  if (outcome === "confirmed" || outcome === "already") {
    return (
      <ReportLinkCard title={outcome === "confirmed" ? "You're all set" : "Already confirmed"}>
        <p role="status">
          This address will get {business ? `${business}'s` : "the"} call reports. Every report has an Unsubscribe
          link at the bottom if you change your mind.
        </p>
      </ReportLinkCard>
    );
  }
  if (outcome === "invalid") {
    return (
      <ReportLinkCard title="This link doesn't work any more">
        <p role="alert">
          Links work once and for 48 hours. Ask the person who added you to send a new one from Reports by email.
        </p>
      </ReportLinkCard>
    );
  }
  return (
    <ReportLinkCard title="Get call reports by email">
      <p>Someone added this address to a business&apos;s call reports. Nothing is sent until you confirm.</p>
      {outcome === "failed" && (
        <p className="text-danger" role="alert">
          Something went wrong. Try again in a moment.
        </p>
      )}
      <Button className="w-full" disabled={busy} onClick={() => void confirm()}>
        {busy ? "Confirming…" : "Yes, send me reports"}
      </Button>
      <p className="text-[13px] text-ink-3">Not expecting this? Close this page and nothing will be sent.</p>
    </ReportLinkCard>
  );
}
