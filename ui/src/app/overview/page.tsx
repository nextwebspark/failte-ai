"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

import { HomeDashboard } from '@/components/dashboard/HomeDashboard';
import { useSelectedAgent } from "@/components/layout/workspaceAgents";
import { useAuth } from '@/lib/auth';
import { greetingFor } from '@/lib/greeting';

/** `?agent=7` → 7; anything else → null (all agents). */
function agentParam(raw: string | null): number | null {
    const id = raw ? Number(raw) : NaN;
    return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * Home: where every member lands. How the phone agents did today, what needs
 * the owner, and when people called, all counted from stored calls.
 *
 * With two or more agents it can show one agent's calls (`?agent=<id>`); an
 * agent's old dashboard address (/workflow/<id>/home) lands here too.
 * `?onboarding=web_call` opens that agent's test panel once.
 */
export default function OverviewPage() {
    const { user } = useAuth();
    const searchParams = useSearchParams();
    const router = useRouter();
    const pathname = usePathname();
    const { agents, select } = useSelectedAgent();
    const agentId = agentParam(searchParams.get("agent"));

    const setParams = useCallback(
        (change: (params: URLSearchParams) => void) => {
            const next = new URLSearchParams(searchParams.toString());
            change(next);
            const query = next.toString();
            router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
        },
        [pathname, router, searchParams],
    );

    // Looking at one agent's Home makes it the menu's agent too.
    useEffect(() => {
        if (agentId !== null && agents?.some((a) => a.id === agentId)) select(agentId);
    }, [agentId, agents, select]);

    const onChange = useCallback(
        (id: number | null) =>
            setParams((params) => {
                if (id === null) params.delete("agent");
                else params.set("agent", String(id));
            }),
        [setParams],
    );
    const onArrivalTestHandled = useCallback(() => setParams((params) => params.delete("onboarding")), [setParams]);

    return (
        <HomeDashboard
            heading={greetingFor(user)}
            workflowId={agentId ?? undefined}
            agentFilter={agents ? { agents, onChange } : undefined}
            testOnArrival={searchParams.get("onboarding") === "web_call"}
            onArrivalTestHandled={onArrivalTestHandled}
        />
    );
}
