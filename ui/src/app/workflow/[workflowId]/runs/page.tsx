"use client";

import { useParams, useSearchParams } from "next/navigation";

import { WorkflowExecutions } from "../components/WorkflowExecutions";

/**
 * "Runs" — the canvas's Analyse section for one agent. The shell supplies the
 * header, the nav and the test rail; this is just the call history.
 */
export default function WorkflowRunsPage() {
    const { workflowId } = useParams();
    const searchParams = useSearchParams();

    return (
        <WorkflowExecutions
            workflowId={Number(workflowId)}
            searchParams={searchParams}
        />
    );
}
