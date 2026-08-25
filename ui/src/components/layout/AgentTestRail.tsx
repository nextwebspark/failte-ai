"use client";

import { useEffect, useMemo, useState } from "react";

import { WorkflowTesterPanel } from "@/app/workflow/[workflowId]/components/WorkflowTesterPanel";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useAgentShell } from "@/context/AgentShellContext";
import { useOnboarding } from "@/context/OnboardingContext";

/**
 * The canvas pins "Test agent" to the right of every agent screen and only
 * ever swaps the centre panel (app-doc/claude-design/Failte AI v2.dc.html, the
 * `inAgent` <aside>). Living in the shell rather than in the flow canvas is
 * what makes that true: the tester keeps its session — transcript, run, mic —
 * while you move between Conversation, Model and voice, Advanced settings.
 *
 * Below xl there is no room for a third column, so the same panel opens as a
 * sheet instead.
 */
export function AgentTestRail() {
  const {
    workflowId,
    agent,
    isRailOpen,
    isSheetOpen,
    setSheetOpen,
    testerDisabledReason,
    emitRuntimeTransition,
  } = useAgentShell();
  const { hasCompletedAction } = useOnboarding();
  const [isDesktopViewport, setIsDesktopViewport] = useState(false);

  useEffect(() => {
    const syncViewport = () => setIsDesktopViewport(window.innerWidth >= 1280);
    syncViewport();
    window.addEventListener("resize", syncViewport);
    return () => window.removeEventListener("resize", syncViewport);
  }, []);

  const showWebCallOnboarding = useMemo(
    () => (agent?.totalRuns ?? 0) === 0 && !hasCompletedAction("web_call_started"),
    [agent?.totalRuns, hasCompletedAction],
  );

  const panelProps = {
    workflowId,
    initialContextVariables: agent?.templateContextVariables,
    disabled: testerDisabledReason !== null,
    disabledReason: testerDisabledReason,
    showWebCallOnboarding,
    onRuntimeNodeTransition: emitRuntimeTransition,
  };

  return (
    <>
      {isRailOpen && (
        // The rail takes a SHARE of the shell rather than a fixed 336px: a
        // transcript at 336px wraps every other word, and on a wide monitor a
        // fixed rail leaves the centre panel absurdly wide. The clamps keep it
        // usable at both ends — never narrower than a readable bubble, never so
        // wide it starves the flow canvas.
        <aside className="hidden w-[32%] min-w-[380px] max-w-[620px] shrink-0 overflow-hidden rounded-[10px] border border-line bg-panel xl:block">
          {/* The rounded panel around it is the surface — the tester paints
              nothing of its own so the shell's three columns match. */}
          <WorkflowTesterPanel
            {...panelProps}
            isVisible={isDesktopViewport}
            className="bg-transparent"
          />
        </aside>
      )}

      <Sheet open={isSheetOpen} onOpenChange={setSheetOpen}>
        {/* Below xl the same panel is a sheet, on the same proportional rule:
            a share of the viewport, capped so it stays a panel and not a page. */}
        <SheetContent
          side="right"
          className="w-full max-w-none p-0 sm:w-[70%] sm:max-w-[640px] xl:hidden"
        >
          <WorkflowTesterPanel {...panelProps} isVisible={isSheetOpen} />
        </SheetContent>
      </Sheet>
    </>
  );
}
