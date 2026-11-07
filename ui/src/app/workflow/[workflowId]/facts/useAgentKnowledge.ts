"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get,
  getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet,
  getWorkflowApiV1WorkflowFetchWorkflowIdGet,
  listBookingsApiV1IntegrationsBookingsGet,
  listConnectionsApiV1IntegrationsConnectionsGet,
  listPhoneNumbersApiV1OrganizationsTelephonyConfigsConfigIdPhoneNumbersGet,
  listTelephonyConfigurationsApiV1OrganizationsTelephonyConfigsGet,
  listToolsApiV1ToolsGet,
  updateWorkflowApiV1WorkflowWorkflowIdPut,
} from "@/client/sdk.gen";
import type { PlatformModelCatalog, WorkflowConfigurationDefaults } from "@/client/types.gen";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { summarizePlatformConfiguration, type VoiceSummary } from "@/lib/platformModelSummary";

import {
  attachedToolUuids,
  type BookingProvider,
  calendarProvider,
  CALENDLY_PROVIDER,
  type Greeting,
  startGreeting,
} from "./knowledge";
import { type VoiceChoices, voiceChoices, withVoice } from "./voiceOptions";

/**
 * Everything around the facts form that the page reads but doesn't edit as
 * text: the greeting, the voice, the calendar and the phone number. Each part
 * loads on its own and is left out ("hidden") when this member may not read
 * it or it can't be loaded, never guessed.
 */

export type Loadable<T> = { state: "loading" } | { state: "hidden" } | ({ state: "ready" } & T);

export type VoiceInfo = Loadable<{
  voice: VoiceSummary | null;
  language: string | null;
  /** The voice and a few others to preview; null when it isn't a platform voice. */
  choices?: VoiceChoices | null;
}>;

/** "none": the agent doesn't book. */
export type CalendarInfo =
  | Loadable<{
      /** Which calendar the agent books with. */
      provider: BookingProvider;
      /** The calendar answers. Null when this member can't tell. */
      connected: boolean | null;
      /** Calendly: the event callers book; null when unknown or none. */
      eventName: string | null;
      /** Calendly with no event chosen yet: the agent takes details instead. */
      needsEvent: boolean;
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
  /** Give this agent *voice* (a `VoiceOption.value`); throws the reason it couldn't. */
  switchVoice?: (voice: string) => Promise<void>;
};

/** What a voice switch saves on top of: the agent's settings and the voice setup calls use. */
type VoiceSaveBase = {
  configurations: Record<string, unknown>;
  configuration: unknown;
  catalog: PlatformModelCatalog;
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

  const voiceBase = useRef<VoiceSaveBase | null>(null);

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

      void loadVoice(configurations).then(({ info, base }) => {
        if (ignore) return;
        voiceBase.current = base;
        setVoice(info);
      });
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

  // The same save the agent's "Model and voice" screen makes: the agent's
  // own platform setup (seeded from the one calls use now) with the new voice.
  const switchVoice = useCallback(
    async (next: string) => {
      const base = voiceBase.current;
      if (!base) throw new Error("The voice settings haven't loaded yet.");
      const configuration = withVoice(base.configuration, base.catalog, next);
      const configurations: Record<string, unknown> = { ...base.configurations };
      delete configurations.model_overrides;
      configurations.model_configuration_v2_override = configuration;
      const res = await updateWorkflowApiV1WorkflowWorkflowIdPut({
        path: { workflow_id: workflowId },
        body: {
          workflow_definition: null,
          workflow_configurations: configurations as WorkflowConfigurationDefaults,
        },
      });
      if (res.error || !res.data) throw new Error(detailFromError(res.error, "Couldn't change the voice. Please try again."));
      const saved = (res.data.workflow_configurations as Record<string, unknown> | null) ?? configurations;
      voiceBase.current = { ...base, configurations: saved, configuration };
      setVoice(voiceInfo(configuration, base.catalog));
    },
    [workflowId],
  );

  return { greeting, voice, calendar, phone, setCalendar: setCalendarState, switchVoice };
}

function voiceInfo(configuration: unknown, catalog: PlatformModelCatalog): VoiceInfo {
  const summary = summarizePlatformConfiguration(configuration, catalog);
  const choices = voiceChoices(configuration, catalog);
  if (summary.kind === "realtime") return { state: "ready", voice: summary.voice, language: summary.language, choices };
  if (summary.kind === "pipeline") {
    return { state: "ready", voice: summary.tts.voice, language: summary.tts.language, choices };
  }
  return { state: "ready", voice: null, language: null, choices: null };
}

/** The voice calls use: this agent's own, else the workspace's. */
async function loadVoice(
  configurations: Record<string, unknown>,
): Promise<{ info: VoiceInfo; base: VoiceSaveBase | null }> {
  const hidden = { info: { state: "hidden" } as VoiceInfo, base: null };
  try {
    const [defaults, workspace] = await Promise.all([
      getModelConfigurationV2DefaultsApiV1OrganizationsModelConfigurationsV2DefaultsGet(),
      getModelConfigurationV2ApiV1OrganizationsModelConfigurationsV2Get(),
    ]);
    const catalog = defaults.data?.platform;
    if (!catalog) return hidden;
    const own = configurations.model_configuration_v2_override as { mode?: string } | undefined;
    const configuration = own?.mode === "platform" ? own : workspace.data?.configuration;
    return { info: voiceInfo(configuration, catalog), base: { configurations, configuration, catalog } };
  } catch {
    return hidden;
  }
}

/**
 * Whether the agent books with a calendar (Google Calendar or Calendly), and how it is.
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
  let provider: BookingProvider | null = null;
  try {
    const tools = await listToolsApiV1ToolsGet({ query: { status: "active" } });
    if (!tools.data) return { state: "hidden" };
    const tool = tools.data.find((t) => attached.has(t.tool_uuid) && calendarProvider(t) !== null);
    calendarTool = tool?.tool_uuid ?? null;
    provider = tool ? calendarProvider(tool) : null;
  } catch {
    return { state: "hidden" };
  }
  if (!calendarTool || !provider) return { state: "none" };

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
  const sameKind = calendars.filter((c) => c.provider === provider);
  const calendar = connection
    ? calendars.find((c) => c.connection_id === connection?.id) ?? null
    : sameKind.length === 1
      ? sameKind[0]
      : null;
  const config = connection?.config ?? {};
  const eventName = typeof config.event_type_name === "string" && config.event_type_name ? config.event_type_name : null;

  return {
    state: "ready",
    provider,
    eventName,
    // Only known with the integrations list (the bookings list has no event).
    needsEvent: provider === CALENDLY_PROVIDER && connection !== null && !config.event_type,
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
