"use client";

import { useParams } from "next/navigation";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import { getWorkflowApiV1WorkflowFetchWorkflowIdGet } from "@/client/sdk.gen";
import type { WorkflowResponse } from "@/client/types.gen";
import type { TextChatInactivityTimeoutConstraints, WidgetTexts } from "@/client/types.gen";
import { FlowEdge, FlowNode } from "@/components/flow/types";
import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";
import {
    type CallDispositionOption,
    resolveWorkflowConfigurations,
    type WorkflowConfigurations,
} from "@/types/workflow-configurations";

import { useWorkflowState } from "../hooks/useWorkflowState";
import { SectionError, SectionSkeleton } from "./SectionStates";

/**
 * Everything a configuration section of an agent needs, loaded once.
 *
 * The nav in the shell now points at several sibling sections — Model and
 * voice, Deployment, Advanced settings — and each of them needs the same
 * thing: the workflow, its resolved configurations, and the savers from
 * useWorkflowState. This wrapper is that shared plumbing, so a section file is
 * only the section.
 */
export type AgentSectionContext = {
    workflow: WorkflowResponse;
    workflowId: number;
    user: { id: string; email?: string };
    workflowName: string;
    /** Resolved (defaults merged in) — never null inside the render prop. */
    workflowConfigurations: WorkflowConfigurations;
    templateContextVariables: Record<string, string>;
    dictionary: string;
    /** Platform defaults for the call disposition editor. */
    defaultCallDispositions: CallDispositionOption[];
    /** Built-in voicemail/screening classifier instructions. */
    defaultAnswerClassifierPrompt: string;
    textChatInactivityTimeoutConstraints: TextChatInactivityTimeoutConstraints | null;
    widgetTextDefaults: WidgetTexts | null;
    saveWorkflowConfigurations: (
        configurations: WorkflowConfigurations,
        workflowName: string,
    ) => Promise<void>;
    saveTemplateContextVariables: (variables: Record<string, string>) => Promise<void>;
    saveDictionary: (dictionary: string) => Promise<void>;
};

export function AgentSectionShell({
    children,
}: {
    children: (context: AgentSectionContext) => ReactNode;
}) {
    const params = useParams();
    const { user, redirectToLogin, loading: authLoading } = useAuth();
    const [workflow, setWorkflow] = useState<WorkflowResponse | undefined>(undefined);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<"failed" | "missing" | null>(null);
    // Bumped by "Try again" to refetch.
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        if (!authLoading && !user) {
            redirectToLogin();
        }
    }, [authLoading, user, redirectToLogin]);

    useEffect(() => {
        let ignore = false;
        const fetchWorkflow = async () => {
            if (!user) return;
            try {
                const response = await getWorkflowApiV1WorkflowFetchWorkflowIdGet({
                    path: { workflow_id: Number(params.workflowId) },
                });
                if (ignore) return;
                if (response.error || !response.data) {
                    setError(response.response?.status === 404 ? "missing" : "failed");
                    return;
                }
                setWorkflow(response.data);
                setError(null);
            } catch (err) {
                if (!ignore) setError("failed");
                logger.error(`Error fetching agent section: ${err}`);
            } finally {
                if (!ignore) setLoading(false);
            }
        };
        if (user) void fetchWorkflow();
        return () => {
            ignore = true;
        };
    // Keyed on the user id, not the object: a fresh user object must not refetch
    // and remount the section under the owner's feet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [params.workflowId, user?.id, attempt]);

    if ((loading || authLoading) && !workflow) return <SectionSkeleton />;

    if (error || !workflow) {
        return (
            <div className="page-body max-w-4xl">
                {error === "failed" ? (
                    <SectionError
                        title="We couldn't load this agent"
                        onRetry={() => {
                            setError(null);
                            setLoading(true);
                            setAttempt((n) => n + 1);
                        }}
                    />
                ) : (
                    <SectionError
                        title="We couldn't find this agent"
                        message="It may have been deleted, or the link is wrong. Go back to All voice agents to pick another."
                    />
                )}
            </div>
        );
    }

    if (!user) return null;

    return (
        <UnsavedChangesProvider>
            <AgentSectionState workflow={workflow} user={user}>
                {children}
            </AgentSectionState>
        </UnsavedChangesProvider>
    );
}

/**
 * Only mounts once the workflow response is in hand, so useWorkflowState never
 * initialises with empty values and overwrites the store.
 */
function AgentSectionState({
    workflow,
    user,
    children,
}: {
    workflow: WorkflowResponse;
    user: { id: string; email?: string };
    children: (context: AgentSectionContext) => ReactNode;
}) {
    const initialFlow = useMemo(
        () => ({
            nodes: workflow.workflow_definition.nodes as FlowNode[],
            edges: workflow.workflow_definition.edges as FlowEdge[],
            viewport: { x: 0, y: 0, zoom: 0 },
        }),
        [workflow],
    );

    const initialTemplateContextVariables = useMemo(
        () => (workflow.template_context_variables as Record<string, string>) || {},
        [workflow],
    );

    const initialWorkflowConfigurations = useMemo(
        () =>
            workflow.workflow_configurations
                ? (workflow.workflow_configurations as WorkflowConfigurations)
                : undefined,
        [workflow],
    );

    const {
        workflowName,
        workflowConfigurations,
        defaultCallDispositions,
        defaultAnswerClassifierPrompt,
        textChatInactivityTimeoutConstraints,
        widgetTextDefaults,
        templateContextVariables,
        dictionary,
        saveWorkflowConfigurations,
        saveTemplateContextVariables,
        saveDictionary,
    } = useWorkflowState({
        initialWorkflowName: workflow.name,
        workflowId: workflow.id,
        initialFlow,
        initialTemplateContextVariables,
        initialWorkflowConfigurations,
        user,
    });

    const resolved = workflowConfigurations
        ? resolveWorkflowConfigurations(workflowConfigurations)
        : null;

    if (!resolved) return <SectionSkeleton />;

    return (
        <>
            {children({
                workflow,
                workflowId: workflow.id,
                user,
                workflowName: workflowName || workflow.name,
                workflowConfigurations: resolved,
                templateContextVariables,
                dictionary,
                defaultCallDispositions,
                defaultAnswerClassifierPrompt,
                textChatInactivityTimeoutConstraints,
                widgetTextDefaults,
                saveWorkflowConfigurations,
                saveTemplateContextVariables,
                saveDictionary,
            })}
        </>
    );
}
