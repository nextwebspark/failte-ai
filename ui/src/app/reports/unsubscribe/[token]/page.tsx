import type { Metadata } from "next";

import { Unsubscribe } from "./Unsubscribe";

export const metadata: Metadata = { title: "Unsubscribe from call reports", robots: { index: false } };

export default async function UnsubscribePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <Unsubscribe token={token} />;
}
