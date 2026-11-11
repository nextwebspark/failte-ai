/**
 * Where "open this agent" goes. Owners land on the agent's dashboard: how it
 * did with calls, what needs them, and its status. Business facts and the
 * call-flow diagram stay one click away in the agent's menu.
 */
export function agentHomeHref(workflowId: number): string {
    return `/workflow/${workflowId}/home`;
}

/** What the agent tells callers: opening hours, address and answers. */
export function agentFactsHref(workflowId: number): string {
    return `/workflow/${workflowId}/facts`;
}

/** The agent's dashboard with the test panel opened once on arrival. */
export function agentTalkHref(workflowId: number): string {
    return `${agentHomeHref(workflowId)}?onboarding=web_call`;
}
