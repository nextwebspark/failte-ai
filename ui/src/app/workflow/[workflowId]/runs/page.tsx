"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { agentCallsHref } from "@/components/workflow/agentLinks";

/**
 * An agent's calls are the Calls page filtered to that agent: one list of
 * calls everywhere. Old links (and the call page's "back") land there.
 */
export default function WorkflowRunsPage() {
    const { workflowId } = useParams<{ workflowId: string }>();
    const router = useRouter();

    useEffect(() => {
        router.replace(agentCallsHref(Number(workflowId)));
    }, [router, workflowId]);

    return null;
}
