"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { HomeSkeleton } from "@/components/dashboard/HomeSkeleton";
import { agentHomeHref } from "@/components/workflow/agentLinks";

/**
 * An agent's dashboard is Home showing that agent's calls. Old links
 * (and bookmarks) to /workflow/<id>/home land there, keeping
 * ?onboarding=web_call so the test panel still opens.
 */
export default function AgentHomePage() {
    const params = useParams<{ workflowId: string }>();
    const searchParams = useSearchParams();
    const router = useRouter();
    const workflowId = Number(params.workflowId);
    const onboarding = searchParams.get("onboarding");

    useEffect(() => {
        const href = agentHomeHref(workflowId);
        router.replace(onboarding ? `${href}&onboarding=${encodeURIComponent(onboarding)}` : href);
    }, [onboarding, router, workflowId]);

    return <HomeSkeleton />;
}
