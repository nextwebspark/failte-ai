import type { Metadata } from "next";

import { SharedRecording } from "./SharedRecording";

// A shared call recording: keep it out of search engines and link previews.
export const metadata: Metadata = {
    title: "Call recording",
    robots: { index: false, follow: false },
    referrer: "no-referrer",
};

export default async function ListenPage({ params }: { params: Promise<{ token: string }> }) {
    const { token } = await params;
    return <SharedRecording token={token} />;
}
