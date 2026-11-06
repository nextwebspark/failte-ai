"use client";

import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { HomeDashboard } from "@/components/dashboard/HomeDashboard";
import { useAgentShell } from "@/context/AgentShellContext";

/**
 * Opening an agent lands here: the same dashboard as Home, for this agent's
 * calls only, under the agent's name.
 */
export default function AgentHomePage() {
    const params = useParams<{ workflowId: string }>();
    const workflowId = Number(params.workflowId);
    const { agent, openTester } = useAgentShell();
    useOpenTesterFromOnboarding(openTester);

    return <HomeDashboard heading={agent?.name ?? "Your agent"} workflowId={workflowId} onTryAgent={openTester} />;
}

/**
 * "Try your agent" links and the create wizard arrive with
 * ?onboarding=web_call: open the test panel once, then drop the flag so a
 * refresh or Back doesn't open it again.
 */
function useOpenTesterFromOnboarding(openTester: () => void) {
    const searchParams = useSearchParams();
    const router = useRouter();
    const pathname = usePathname();
    const opened = useRef(false);

    useEffect(() => {
        if (opened.current || searchParams.get("onboarding") !== "web_call") return;
        opened.current = true;
        openTester();
        const next = new URLSearchParams(searchParams.toString());
        next.delete("onboarding");
        const query = next.toString();
        router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    }, [openTester, pathname, router, searchParams]);
}
