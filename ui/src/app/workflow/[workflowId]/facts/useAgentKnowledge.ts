"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get,
  getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet,
  getWorkflowApiV1WorkflowFetchWorkflowIdGet,
  listBookingsApiV1IntegrationsBookingsGet,
  listConnectionsApiV1IntegrationsConnectionsGet,
  listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet,
  listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet,
  listToolsApiV1ToolsGet,
} from "@/client/sdk.gen";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";
import { summarizePlatformConfiguration, type VoiceSummary } from "@/lib/platformModelSummary";

import { attachedToolUuids, type Greeting, isCalendarTool, startGreeting } from "./knowledge";

/**
 * Everything around the facts form that the page reads but doesn't edit as
 * text: the greeting, the voice, the calendar and the phone number. Each part
 * loads on its own and is left out ("hidden") when this member may not read
 * it or it can't be loaded, never guessed.
 */

export type Loadable<T> = { state: "loading" } | { state: "hidden" } | ({ state: "ready" } & T);

export type VoiceInfo = Loadable<{ voice: VoiceSummary | null; language: string | null }>;

/** "none": the agent doesn't book. */
export type CalendarInfo =
  | Loadable<{
      /** Google Calendar answers. Null when this member can't tell. */
      connected: boolean | null;
      /** The owner's switch on the calendar. Null when this member can't tell. */
      aiBooking: boolean | null;
      connectionId: string | null;
      rules: unknown;
    }>
  | { state: "none" };

export type PhoneInfo = Loadable<{ numbers: string[] }>;

export type AgentKnowledge = {
  greeting: Loadable<{ greeting: Greeting }>;
  voice: VoiceInfo;
  calendar: CalendarInfo;
  phone: PhoneInfo;
  setCalendar: (update: (current: CalendarInfo) => CalendarInfo) => void;
};

export function useAgentKnowledge(workflowId: number): AgentKnowledge {
  const { user, loading: authLoading, getAccessToken } = useAuth();
  const { can, orgContext } = useOrgConfig();
  const permissionsKnown = orgContext !== null;
  const may = useCallback(
    (permission: Parameters<typeof can>[0]) => !permissionsKnown || can(permission),
    [permissionsKnown, can],
  );

  const [greeting, setGreeting] = useState<AgentKnowledge["greeting"]>({ state: "loading" });
  const [voice, setVoice] = useState<VoiceInfo>({ state: "loading" });
  const [calendar, setCalendarState] = useState<CalendarInfo>({ state: "loading" });
  const [phone, setPhone] = useState<PhoneInfo>({ state: "loading" });

  const ready = !authLoading && Boolean(user);
  const userId = user?.id;

  // The agent itself: its greeting, its voice override and its tools.
  useEffect(() => {
    if (!ready) return;
    let ignore = false;
    const load = async () => {
      let definition: unknown = null;
      let configurations: Record<string, unknown> = {};
      try {
        const res = await getWorkflowApiV1WorkflowFetchWorkflowIdGet({ path: { workflow_id: workflowId } });
        if (!res.data) throw new Error("agent");
        definition = res.data.workflow_definition;
        configurations = (res.data.workflow_configurations as Record<string, unknown> | null) ?? {};
        if (!ignore) setGreeting({ state: "ready", greeting: startGreeting(definition) });
      } catch {
        if (!ignore) {
          setGreeting({ state: "hidden" });
          setVoice({ state: "hidden" });
          setCalendarState({ state: "hidden" });
        }
        return;
      }

      void loadVoice(configurations).then((info) => !ignore && setVoice(info));
      void loadCalendar(definition, may).then((info) => !ignore && setCalendarState(info));
    };
    void load();
    return () => {
      ignore = true;
    };
    // `may` changes once the role is known; the agent needn't be read again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, userId, workflowId, permissionsKnown]);

  // The numbers that ring this agent, for members who may see phone settings.
  const canReadPhones = may("telephony:read");
  useEffect(() => {
    if (!ready) return;
    if (!canReadPhones) {
      setPhone({ state: "hidden" });
      return;
    }
    let ignore = false;
    const load = async () => {
      try {
        const headers = { Authorization: `Bearer ${await getAccessToken()}` };
        const list = await listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet({ headers });
        if (list.error) throw new Error("phones");
        const perProvider = await Promise.all(
          (list.data?.configurations ?? []).map(async (config) => {
            const res = await listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet({
              headers,
              path: { config_id: config.id },
            });
            if (res.error) throw new Error("phones");
            return res.data?.phone_numbers ?? [];
          }),
        );
        const numbers = perProvider
          .flat()
          .filter((n) => n.inbound_workflow_id === workflowId && n.is_active)
          .map((n) => n.address);
        if (!ignore) setPhone({ state: "ready", numbers });
      } catch {
        if (!ignore) setPhone({ state: "hidden" });
      }
    };
    void load();
    return () => {
      ignore = true;
    };
    // Not keyed on getAccessToken: a new function each render must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, userId, canReadPhones, workflowId]);

  return { greeting, voice, calendar, phone, setCalendar: setCalendarState };
}

/** The voice calls use: this agent's own, else the workspace's. */
async function loadVoice(configurations: Record<string, unknown>): Promise<VoiceInfo> {
  try {
    const [defaults, workspace] = await Promise.all([
      getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet(),
      getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get(),
    ]);
    const catalog = defaults.data?.platform;
    if (!catalog) return { state: "hidden" };
    const own = configurations.model_configuration_v2_override as { mode?: string } | undefined;
    const configuration = own?.mode === "platform" ? own : workspace.data?.configuration;
    const summary = summarizePlatformConfiguration(configuration, catalog);
    if (summary.kind === "realtime") return { state: "ready", voice: summary.voice, language: summary.language };
    if (summary.kind === "pipeline") return { state: "ready", voice: summary.tts.voice, language: summary.tts.language };
    return { state: "ready", voice: null, language: null };
  } catch {
    return { state: "hidden" };
  }
}

/**
 * Whether the agent books with Google Calendar, and how that calendar is.
 * The calendar's switch and booking rules come from the bookings list (every
 * member who sees calls may read it); which connection is this agent's needs
 * the integrations list, so without it a single calendar is assumed only
 * when the workspace has exactly one.
 */
async function loadCalendar(
  definition: unknown,
  may: (permission: "integrations:read" | "calls:read" | "agents:read") => boolean,
): Promise<CalendarInfo> {
  const attached = attachedToolUuids(definition);
  if (attached.size === 0) return { state: "none" };
  let calendarTool: string | null = null;
  try {
    const tools = await listToolsApiV1ToolsGet({ query: { status: "active" } });
    if (!tools.data) return { state: "hidden" };
    calendarTool = tools.data.find((tool) => attached.has(tool.tool_uuid) && isCalendarTool(tool))?.tool_uuid ?? null;
  } catch {
    return { state: "hidden" };
  }
  if (!calendarTool) return { state: "none" };

  let connection: { id: string; status: string; config?: Record<string, unknown> } | null = null;
  if (may("integrations:read")) {
    try {
      const res = await listConnectionsApiV1IntegrationsConnectionsGet();
      connection = res.data?.connections.find((c) => c.tool_uuids?.includes(calendarTool as string)) ?? null;
    } catch {
      // Fall back to the bookings list below.
    }
  }

  type Calendar = { connection_id: string; ai_booking_enabled: boolean; rules?: unknown; ok?: boolean; provider: string };
  let calendars: Calendar[] = [];
  if (may("calls:read")) {
    try {
      const start = new Date();
      const end = new Date(start.getTime() + 60_000);
      const res = await listBookingsApiV1IntegrationsBookingsGet({
        query: { start: start.toISOString(), end: end.toISOString() },
      });
      calendars = (res.data?.calendars ?? []) as Calendar[];
    } catch {
      // Shown without the switch and the hours.
    }
  }
  const google = calendars.filter((c) => c.provider.includes("google"));
  const calendar = connection
    ? calendars.find((c) => c.connection_id === connection?.id) ?? null
    : google.length === 1
      ? google[0]
      : null;

  return {
    state: "ready",
    connected: calendar ? calendar.ok !== false : connection ? connection.status === "active" : null,
    aiBooking: calendar
      ? calendar.ai_booking_enabled
      : connection
        ? connection.config?.ai_booking_enabled !== false
        : null,
    connectionId: calendar?.connection_id ?? connection?.id ?? null,
    rules: calendar?.rules ?? connection?.config ?? null,
  };
}
