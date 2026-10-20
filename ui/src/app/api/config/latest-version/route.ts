import { NextResponse } from "next/server";

// Upstream checked ghcr.io for the newest dograh-hq/dograh-{ui,api} image tags
// and nudged self-hosters to upgrade. Those are Dograh's releases, not ours,
// and LightMove.ai publishes no public images, so there is nothing to compare
// against: report no newer release and make no outbound request.
export async function GET() {
  return NextResponse.json({ latest: null }, { status: 200 });
}
