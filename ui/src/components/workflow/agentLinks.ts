/**
 * Where "open this agent" goes: Home showing this agent's calls, what needs
 * the owner, and its status. Business facts and the call-flow diagram are in
 * the menu's Agent section, which follows the agent opened.
 */
export function agentHomeHref(workflowId: number): string {
    return `/overview?agent=${workflowId}`;
}

/** What the agent tells callers: opening hours, address and answers. */
export function agentFactsHref(workflowId: number): string {
    return `/workflow/${workflowId}/facts`;
}

/** Home for this agent, with its test panel opened once on arrival. */
export function agentTalkHref(workflowId: number): string {
    return `${agentHomeHref(workflowId)}&onboarding=web_call`;
}

/** The Calls page showing only this agent's calls. */
export function agentCallsHref(workflowId: number): string {
    const filters = JSON.stringify([{ id: "workflowId", value: { value: workflowId } }]);
    return `/usage?${new URLSearchParams({ filters })}`;
}
