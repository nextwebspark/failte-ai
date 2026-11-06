import type { Metadata } from "next";

import { ConfirmReports } from "./ConfirmReports";

export const metadata: Metadata = { title: "Confirm call reports", robots: { index: false } };

export default async function ConfirmReportsPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ConfirmReports token={token} />;
}
