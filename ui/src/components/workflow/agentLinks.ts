/**
 * Where "open this agent" goes. Owners land on the agent's summary and
 * Business facts — plain words they understand — rather than on the call-flow
 * diagram, which stays one click away under Conversation.
 */
export function agentHomeHref(workflowId: number): string {
    return `/workflow/${workflowId}/facts`;
}

/** The agent's home with the test panel opened once on arrival. */
export function agentTalkHref(workflowId: number): string {
    return `${agentHomeHref(workflowId)}?onboarding=web_call`;
}
